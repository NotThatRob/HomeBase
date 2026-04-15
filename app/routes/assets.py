import os
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.config import get_settings
from app.database import get_db
from app.services.assets import (
    CATEGORIES,
    create_asset,
    get_asset,
    list_assets,
    retire_asset,
    save_photo,
    update_asset,
)
from app.services.components import get_preset_components, list_components
from app.services.cost_service import (
    get_asset_actual_spend_trend,
    get_asset_cost_composition,
    get_asset_ownership_summary,
)
from app.services.fuel_logs import calculate_mpg, get_fuel_summary
from app.services.maintenance_tasks import computed_status, list_tasks_for_asset
from app.services.recurring_costs import get_recurring_summary
from app.services.service_records import get_service_summary
from app.services.validation import (
    MAX_MILEAGE,
    ensure_long_text,
    ensure_nonnegative_int,
    ensure_positive_money,
    ensure_short_text,
    ensure_year_in_range,
)

router = APIRouter(prefix="/assets", tags=["assets"])


def _upload_path(upload_dir: str, relative_path: str) -> str | None:
    relative_path = relative_path.lstrip("/\\")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = Path(upload_dir).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return str(candidate)


@router.get("", response_class=HTMLResponse)
def asset_list(
    request: Request,
    category: str | None = None,
    include_retired: bool = False,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    assets = list_assets(db, user, category=category, include_retired=include_retired)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/list.html",
        {
            "assets": assets,
            "categories": CATEGORIES,
            "selected_category": category,
            "include_retired": include_retired,
            "user": user,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def asset_new(request: Request):
    user = get_current_user(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/form.html",
        {"categories": CATEGORIES, "asset": None, "user": user},
    )


def _parse_asset_form(raw: dict) -> dict:
    data = dict(raw)
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    if data.get("year"):
        try:
            data["year"] = int(str(data["year"]).strip())
        except ValueError as exc:
            raise ValueError("Year must be a whole number") from exc
    if data.get("purchase_price"):
        try:
            data["purchase_price"] = Decimal(str(data["purchase_price"]).replace(",", "").strip())
        except InvalidOperation as exc:
            raise ValueError("Purchase price must be a number") from exc
    if data.get("current_mileage"):
        try:
            data["current_mileage"] = int(str(data["current_mileage"]).replace(",", "").strip())
        except ValueError as exc:
            raise ValueError("Mileage must be a whole number") from exc

    ensure_short_text(data.get("name"), "Name")
    ensure_short_text(data.get("make"), "Make")
    ensure_short_text(data.get("model_name"), "Model")
    ensure_short_text(data.get("serial_number"), "Serial number")
    ensure_short_text(data.get("location"), "Location")
    ensure_short_text(data.get("purchase_vendor"), "Purchase vendor")
    ensure_short_text(data.get("subcategory"), "Subcategory")
    ensure_short_text(data.get("license_plate"), "License plate")
    ensure_short_text(data.get("vin"), "VIN")
    ensure_short_text(data.get("fuel_type"), "Fuel type")
    ensure_long_text(data.get("notes"), "Notes")
    ensure_long_text(data.get("warranty_notes"), "Warranty notes")
    ensure_long_text(data.get("insurance_info"), "Insurance info")
    ensure_year_in_range(data.get("year"))
    ensure_nonnegative_int(data.get("current_mileage"), "Mileage", upper=MAX_MILEAGE)
    ensure_positive_money(data.get("purchase_price"), "Purchase price", allow_zero=True)
    return data


def _render_asset_form_error(request: Request, user, asset, error: str):
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/form.html",
        {"categories": CATEGORIES, "asset": asset, "user": user, "error": error},
        status_code=400,
    )


@router.post("")
async def asset_create(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    form = await request.form()
    data = dict(form)

    # Handle file upload separately
    photo_file: UploadFile | None = data.pop("photo", None)

    try:
        data = _parse_asset_form(data)
    except ValueError as exc:
        return _render_asset_form_error(request, user, None, str(exc))

    try:
        asset = create_asset(db, data, user)
    except ValueError as exc:
        return _render_asset_form_error(request, user, None, str(exc))

    # Handle photo upload
    if photo_file and photo_file.filename:
        settings = get_settings()
        try:
            relative_path = await save_photo(asset.id, photo_file, settings.upload_dir)
        except ValueError as exc:
            return _render_asset_form_error(request, user, asset, str(exc))
        asset.photo = relative_path
        db.commit()

    return RedirectResponse(url=f"/assets/{asset.id}", status_code=303)


@router.get("/partials/vehicle-fields", response_class=HTMLResponse)
def vehicle_fields_partial(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/vehicle_fields.html",
        {"asset": None},
    )


SERVICE_HISTORY_PREVIEW_LIMIT = 5
DOCUMENTS_PREVIEW_LIMIT = 3
RECURRING_COSTS_PREVIEW_LIMIT = 5
FUEL_LOGS_PREVIEW_LIMIT = 5


def _asset_documents(asset) -> list:
    """Asset-level documents — exclude those tied to a specific service record."""
    return [d for d in asset.documents if d.service_record_id is None]


def _filter_by_component(items, component_id):
    """Keep only items tagged with the given component. Python-side because
    record/document lists are small per-asset and M2M eager load is already
    available through the relationship."""
    if component_id is None:
        return items
    return [i for i in items if any(c.id == component_id for c in i.components)]


def _summary_from_records(records):
    """Compute total_cost / record_count / last_service_date from an in-memory
    list. Used when filtering by component so the headline stats match the
    timeline below them."""
    if not records:
        return {
            "total_cost": Decimal("0"),
            "record_count": 0,
            "last_service_date": None,
        }
    return {
        "total_cost": sum((r.cost for r in records), Decimal("0")),
        "record_count": len(records),
        "last_service_date": max(r.service_date for r in records),
    }


def _resolve_component(asset, component_id):
    """Return the Component on this asset matching the id, or None.

    We match against ``asset.components`` (not a DB lookup) so a component
    from another asset can't be smuggled in via query param.
    """
    if component_id is None:
        return None
    return next((c for c in asset.components if c.id == component_id), None)


def _asset_trend_chart_payload(trend: list[dict], *, include_fuel: bool) -> dict:
    payload = {
        "labels": [row["label"] for row in trend],
        "service": [float(row["service"]) for row in trend],
        "total": [float(row["total"]) for row in trend],
    }
    if include_fuel:
        payload["fuel"] = [float(row["fuel"]) for row in trend]
    return payload


def _asset_composition_chart_payload(composition: dict, *, include_fuel: bool) -> dict:
    rows = [
        ("Purchase", composition["purchase_price"]),
        ("Service", composition["service_total"]),
    ]
    if include_fuel or composition["fuel_total"] > 0:
        rows.append(("Fuel", composition["fuel_total"]))
    rows.append(("Annual Recurring", composition["annual_recurring"]))

    non_zero = [(label, value) for label, value in rows if value > 0]
    return {
        "labels": [label for label, _ in non_zero],
        "values": [float(value) for _, value in non_zero],
    }


@router.get("/{asset_id}", response_class=HTMLResponse)
def asset_detail(
    request: Request,
    asset_id: uuid.UUID,
    component: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    components = list_components(db, asset_id)
    preset_names = get_preset_components(asset.category)

    active_component = _resolve_component(asset, component)
    active_component_id = active_component.id if active_component else None

    asset_docs = _filter_by_component(_asset_documents(asset), active_component_id)
    documents_total = len(asset_docs)
    documents_preview = asset_docs[:DOCUMENTS_PREVIEW_LIMIT]

    all_records = _filter_by_component(list(asset.service_records), active_component_id)
    records_preview = all_records[:SERVICE_HISTORY_PREVIEW_LIMIT]
    records_total = len(all_records)
    recurring_costs = list(asset.recurring_costs)
    recurring_costs_preview = recurring_costs[:RECURRING_COSTS_PREVIEW_LIMIT]
    recurring_costs_total = len(recurring_costs)
    fuel_logs = list(asset.fuel_logs) if asset.category == "vehicle" else []
    fuel_logs_preview = fuel_logs[:FUEL_LOGS_PREVIEW_LIMIT]
    fuel_logs_total = len(fuel_logs)
    maintenance_tasks = list_tasks_for_asset(db, asset_id)
    maintenance_tasks = _filter_by_component(maintenance_tasks, active_component_id)

    if active_component:
        service_summary = _summary_from_records(all_records)
    else:
        service_summary = get_service_summary(db, asset_id)

    ownership_summary = get_asset_ownership_summary(db, asset_id)
    asset_spend_trend = get_asset_actual_spend_trend(db, asset_id, months=12)
    asset_cost_composition = get_asset_cost_composition(db, asset_id)
    include_fuel_charts = asset.category == "vehicle"

    return request.app.state.templates.TemplateResponse(
        request,
        "assets/detail.html",
        {
            "asset": asset,
            "user": user,
            "components": components,
            "preset_names": preset_names,
            "service_summary": service_summary,
            "ownership_summary": ownership_summary,
            "asset_spend_trend_chart": _asset_trend_chart_payload(
                asset_spend_trend,
                include_fuel=include_fuel_charts,
            ),
            "asset_cost_composition_chart": _asset_composition_chart_payload(
                asset_cost_composition,
                include_fuel=include_fuel_charts,
            ),
            "include_fuel_charts": include_fuel_charts,
            "today": date.today(),
            "documents": documents_preview,
            "documents_total": documents_total,
            "documents_show_view_all": documents_total > DOCUMENTS_PREVIEW_LIMIT,
            "records": records_preview,
            "records_show_view_all": records_total > SERVICE_HISTORY_PREVIEW_LIMIT,
            "recurring_costs": recurring_costs_preview,
            "recurring_summary": get_recurring_summary(db, asset_id),
            "recurring_costs_show_view_all": (
                recurring_costs_total > RECURRING_COSTS_PREVIEW_LIMIT
            ),
            "fuel_logs": fuel_logs_preview,
            "fuel_summary": (
                get_fuel_summary(db, asset_id)
                if asset.category == "vehicle"
                else {"fillup_count": 0}
            ),
            "fuel_mpg_by_id": calculate_mpg(fuel_logs),
            "fuel_logs_show_view_all": fuel_logs_total > FUEL_LOGS_PREVIEW_LIMIT,
            "maintenance_tasks": maintenance_tasks,
            "computed_status": computed_status,
            "active_component": active_component,
        },
    )


@router.get("/{asset_id}/photo")
def asset_photo(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    if not asset.photo:
        return HTMLResponse("Photo not found", status_code=404)

    settings = get_settings()
    abs_path = _upload_path(settings.upload_dir, asset.photo)
    if not abs_path or not os.path.isfile(abs_path):
        return HTMLResponse("Photo not found", status_code=404)

    ext = os.path.splitext(asset.photo)[1].lower() or ".jpg"
    return FileResponse(
        abs_path,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="photo{ext}"',
        },
    )


@router.get("/{asset_id}/partials/service-history", response_class=HTMLResponse)
def asset_service_history_partial(
    request: Request,
    asset_id: uuid.UUID,
    component: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    active_component = _resolve_component(asset, component)
    active_component_id = active_component.id if active_component else None

    records = _filter_by_component(list(asset.service_records), active_component_id)
    if active_component:
        service_summary = _summary_from_records(records)
    else:
        service_summary = get_service_summary(db, asset_id)

    return request.app.state.templates.TemplateResponse(
        request,
        "assets/partials/service_history_section.html",
        {
            "asset": asset,
            "records": records,
            "service_summary": service_summary,
            "show_view_all": False,
            "active_component": active_component,
        },
    )


@router.get("/{asset_id}/partials/fuel-logs", response_class=HTMLResponse)
def asset_fuel_logs_partial(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    if asset.category != "vehicle":
        return HTMLResponse("Fuel logs are only available for vehicles", status_code=400)
    fuel_logs = list(asset.fuel_logs)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/partials/fuel_logs_section.html",
        {
            "asset": asset,
            "fuel_logs": fuel_logs,
            "fuel_summary": get_fuel_summary(db, asset_id),
            "fuel_mpg_by_id": calculate_mpg(fuel_logs),
            "show_view_all": False,
        },
    )


@router.get("/{asset_id}/partials/recurring-costs", response_class=HTMLResponse)
def asset_recurring_costs_partial(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/partials/recurring_costs_section.html",
        {
            "asset": asset,
            "recurring_costs": list(asset.recurring_costs),
            "recurring_summary": get_recurring_summary(db, asset_id),
            "show_view_all": False,
        },
    )


@router.get("/{asset_id}/partials/documents", response_class=HTMLResponse)
def asset_documents_partial(
    request: Request,
    asset_id: uuid.UUID,
    component: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    active_component = _resolve_component(asset, component)
    active_component_id = active_component.id if active_component else None
    docs = _filter_by_component(_asset_documents(asset), active_component_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/partials/documents_section.html",
        {
            "asset": asset,
            "documents": docs,
            "documents_total": len(docs),
            "show_view_all": False,
            "active_component": active_component,
        },
    )


@router.get("/{asset_id}/edit", response_class=HTMLResponse)
def asset_edit(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/form.html",
        {"categories": CATEGORIES, "asset": asset, "user": user},
    )


@router.post("/{asset_id}/edit")
async def asset_update(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    form = await request.form()
    data = dict(form)

    # Handle file upload separately
    photo_file: UploadFile | None = data.pop("photo", None)

    try:
        data = _parse_asset_form(data)
    except ValueError as exc:
        return _render_asset_form_error(request, user, asset, str(exc))

    try:
        asset = update_asset(db, asset, data)
    except ValueError as exc:
        return _render_asset_form_error(request, user, asset, str(exc))

    # Handle photo upload
    if photo_file and photo_file.filename:
        settings = get_settings()
        try:
            relative_path = await save_photo(asset.id, photo_file, settings.upload_dir)
        except ValueError as exc:
            return _render_asset_form_error(request, user, asset, str(exc))
        asset.photo = relative_path
        db.commit()

    return RedirectResponse(url=f"/assets/{asset.id}", status_code=303)


@router.post("/{asset_id}/delete")
def asset_retire(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    retire_asset(db, asset)
    return RedirectResponse(url="/assets", status_code=303)

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.database import get_db
from app.services.assets import get_asset, list_assets
from app.services.fuel_logs import (
    calculate_mpg,
    create_fuel_log,
    delete_fuel_log,
    get_fuel_log,
    list_fuel_logs,
    update_fuel_log,
)

router = APIRouter(prefix="/assets/{asset_id}/fuel-logs", tags=["fuel_logs"])
quick_router = APIRouter(tags=["fuel_logs"])


def _parse_form(raw: dict) -> dict:
    data = dict(raw)
    data.pop("csrf_token", None)
    data["full_tank"] = "full_tank" in data
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    for field in ("gallons", "cost_per_gallon", "total_cost"):
        if data.get(field) is not None:
            try:
                data[field] = Decimal(str(data[field]).replace(",", ""))
            except InvalidOperation as exc:
                raise ValueError(f"Invalid {field.replace('_', ' ')}") from exc

    if data.get("mileage_at_fillup") is not None:
        try:
            data["mileage_at_fillup"] = int(str(data["mileage_at_fillup"]).replace(",", ""))
        except ValueError as exc:
            raise ValueError("Invalid mileage at fillup") from exc

    if isinstance(data.get("fillup_date"), str):
        try:
            data["fillup_date"] = datetime.strptime(data["fillup_date"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Invalid fillup date") from exc
    return data


def _visible_active_vehicles(db: Session, user) -> list:
    return [
        asset for asset in list_assets(db, user, category="vehicle") if asset.status != "retired"
    ]


def _vehicle_asset_or_response(asset):
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    if asset.category != "vehicle":
        return HTMLResponse("Fuel logs are only available for vehicles", status_code=400)
    if asset.status == "retired":
        return HTMLResponse("Cannot add fuel logs to retired assets", status_code=400)
    return None


def _form_context(asset, log, user) -> dict:
    return {
        "asset": asset,
        "log": log,
        "today": date.today(),
        "user": user,
    }


@quick_router.get("/fuel-logs/new", response_class=HTMLResponse)
def fuel_log_quick_new(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    vehicles = _visible_active_vehicles(db, user)
    if len(vehicles) == 1:
        return RedirectResponse(
            url=f"/assets/{vehicles[0].id}/fuel-logs/new",
            status_code=303,
        )
    return request.app.state.templates.TemplateResponse(
        request,
        "fuel_logs/picker.html",
        {"vehicles": vehicles, "user": user},
    )


@router.get("/new", response_class=HTMLResponse)
def fuel_log_new(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if response := _vehicle_asset_or_response(asset):
        return response
    check_asset_access(asset, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "fuel_logs/form.html",
        _form_context(asset, None, user),
    )


@router.post("")
async def fuel_log_create(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if response := _vehicle_asset_or_response(asset):
        return response
    check_asset_access(asset, user, require_owner=True)

    try:
        data = _parse_form(await request.form())
        create_fuel_log(db, asset, data, user)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.get("/{log_id}", response_class=HTMLResponse)
def fuel_log_detail(
    request: Request,
    asset_id: uuid.UUID,
    log_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    log = get_fuel_log(db, log_id)
    if not asset or not log or log.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user)
    mpg_by_id = calculate_mpg(list_fuel_logs(db, asset_id))
    return request.app.state.templates.TemplateResponse(
        request,
        "fuel_logs/detail.html",
        {
            "asset": asset,
            "log": log,
            "mpg": mpg_by_id.get(log.id),
            "user": user,
        },
    )


@router.get("/{log_id}/edit", response_class=HTMLResponse)
def fuel_log_edit(
    request: Request,
    asset_id: uuid.UUID,
    log_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    log = get_fuel_log(db, log_id)
    if not asset or not log or log.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    if response := _vehicle_asset_or_response(asset):
        return response
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "fuel_logs/form.html",
        _form_context(asset, log, user),
    )


@router.post("/{log_id}/edit")
async def fuel_log_update(
    request: Request,
    asset_id: uuid.UUID,
    log_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    log = get_fuel_log(db, log_id)
    if not asset or not log or log.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    if response := _vehicle_asset_or_response(asset):
        return response
    check_asset_access(asset, user, require_owner=True)

    try:
        data = _parse_form(await request.form())
        update_fuel_log(db, asset, log, data)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{log_id}/delete")
def fuel_log_delete(
    request: Request,
    asset_id: uuid.UUID,
    log_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    log = get_fuel_log(db, log_id)
    if not asset or not log or log.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    delete_fuel_log(db, log)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.service_record import COST_CATEGORIES
from app.services.assets import get_asset
from app.services.documents import create_document, save_document
from app.services.service_records import (
    create_service_record,
    delete_service_record,
    get_service_record,
    update_service_record,
)

logger = logging.getLogger(__name__)


async def _save_attached_documents(
    db: Session,
    asset_id: uuid.UUID,
    service_record_id: uuid.UUID,
    files: list[UploadFile],
    user,
) -> None:
    """Best-effort: save each uploaded file as a Document linked to the record.

    Failures are logged but do not roll back the parent service record. The
    user can re-upload anything that fails from the document UI.
    """
    if not files:
        return
    settings = get_settings()
    for upload in files:
        if not getattr(upload, "filename", ""):
            continue
        try:
            file_meta = await save_document(asset_id, upload, settings.upload_dir)
            create_document(
                db,
                asset_id,
                {"title": file_meta["file_name"], "doc_type": "receipt"},
                file_meta,
                user,
                service_record_id=service_record_id,
            )
        except (ValueError, OSError) as exc:
            logger.warning(
                "Failed to attach upload %r to service record %s: %s",
                getattr(upload, "filename", "?"),
                service_record_id,
                exc,
            )

router = APIRouter(
    prefix="/assets/{asset_id}/service-records", tags=["service_records"]
)


@router.get("/new", response_class=HTMLResponse)
def service_record_new(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user)
    if asset.status == "retired":
        return HTMLResponse("Cannot add service records to retired assets", status_code=400)
    return request.app.state.templates.TemplateResponse(
        request,
        "service_records/form.html",
        {
            "asset": asset,
            "record": None,
            "cost_categories": COST_CATEGORIES,
            "today": date.today(),
            "user": user,
        },
    )


@router.post("")
async def service_record_create(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    if asset.status == "retired":
        return HTMLResponse("Cannot add service records to retired assets", status_code=400)

    raw_form = await request.form()
    data = dict(raw_form)

    # Extract component_ids (multi-value checkbox field)
    try:
        component_ids = [
            uuid.UUID(v) for v in raw_form.getlist("component_ids")
        ]
    except ValueError:
        return HTMLResponse("Invalid component id", status_code=400)
    data.pop("component_ids", None)

    # Pull off any uploaded files before they get coerced into form data.
    documents_files = [
        f for f in raw_form.getlist("documents") if getattr(f, "filename", "")
    ]
    data.pop("documents", None)

    # Checkbox: present = "on", absent = not in data
    data["is_diy"] = "is_diy" in data

    # Clean empty strings to None
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    try:
        if data.get("mileage_at_service"):
            data["mileage_at_service"] = int(
                str(data["mileage_at_service"]).replace(",", "").strip()
            )
        record = create_service_record(db, asset_id, data, user, component_ids)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    await _save_attached_documents(db, asset_id, record.id, documents_files, user)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.get("/{record_id}", response_class=HTMLResponse)
def service_record_detail(
    request: Request,
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    record = get_service_record(db, record_id)
    if not asset or not record or record.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "service_records/detail.html",
        {"asset": asset, "record": record, "user": user},
    )


@router.get("/{record_id}/edit", response_class=HTMLResponse)
def service_record_edit(
    request: Request,
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    record = get_service_record(db, record_id)
    if not asset or not record or record.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "service_records/form.html",
        {
            "asset": asset,
            "record": record,
            "cost_categories": COST_CATEGORIES,
            "today": date.today(),
            "user": user,
        },
    )


@router.post("/{record_id}/edit")
async def service_record_update(
    request: Request,
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    record = get_service_record(db, record_id)
    if not asset or not record or record.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    raw_form = await request.form()
    data = dict(raw_form)

    try:
        component_ids = [
            uuid.UUID(v) for v in raw_form.getlist("component_ids")
        ]
    except ValueError:
        return HTMLResponse("Invalid component id", status_code=400)
    data.pop("component_ids", None)

    documents_files = [
        f for f in raw_form.getlist("documents") if getattr(f, "filename", "")
    ]
    data.pop("documents", None)

    data["is_diy"] = "is_diy" in data

    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    try:
        if data.get("mileage_at_service"):
            data["mileage_at_service"] = int(
                str(data["mileage_at_service"]).replace(",", "").strip()
            )
        update_service_record(db, record, data, component_ids)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    await _save_attached_documents(db, asset_id, record.id, documents_files, user)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{record_id}/delete")
def service_record_delete(
    request: Request,
    asset_id: uuid.UUID,
    record_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    record = get_service_record(db, record_id)
    if not asset or not record or record.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    delete_service_record(db, record)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)

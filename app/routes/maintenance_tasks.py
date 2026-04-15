import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.database import get_db
from app.models.maintenance_task import INTERVAL_UNITS, SCHEDULE_TYPES, TASK_PRIORITIES
from app.models.service_record import COST_CATEGORIES
from app.routes.service_records import _save_attached_documents
from app.services.assets import get_asset
from app.services.maintenance_tasks import (
    complete_task,
    computed_status,
    create_task,
    delete_task,
    get_task,
    list_tasks_for_asset,
    set_task_status,
    update_task,
)
from app.services.service_records import create_service_record

router = APIRouter(
    prefix="/assets/{asset_id}/maintenance-tasks",
    tags=["maintenance_tasks"],
)


def _task_form_context(request: Request, asset, task, user, **overrides) -> dict:
    context = {
        "asset": asset,
        "task": task,
        "user": user,
        "schedule_types": SCHEDULE_TYPES,
        "interval_units": INTERVAL_UNITS,
        "priorities": TASK_PRIORITIES,
        "today": date.today(),
        "error": None,
    }
    context.update(overrides)
    return context


def _clean_task_form(raw_form) -> tuple[dict, list[uuid.UUID]]:
    data = dict(raw_form)
    data.pop("csrf_token", None)
    try:
        component_ids = [uuid.UUID(v) for v in raw_form.getlist("component_ids")]
    except ValueError as exc:
        raise ValueError("Invalid component id") from exc
    data.pop("component_ids", None)

    for key in list(data.keys()):
        if isinstance(data[key], str):
            data[key] = data[key].strip()
            if data[key] == "":
                data[key] = None

    for key in [
        "interval_value",
        "calendar_month",
        "calendar_day",
        "usage_trigger_value",
        "next_due_usage_value",
    ]:
        if data.get(key):
            data[key] = int(str(data[key]).replace(",", ""))

    return data, component_ids


@router.get("/new", response_class=HTMLResponse)
def maintenance_task_new(
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
        return HTMLResponse("Cannot add maintenance tasks to retired assets", status_code=400)
    return request.app.state.templates.TemplateResponse(
        request,
        "maintenance_tasks/form.html",
        _task_form_context(request, asset, None, user),
    )


@router.post("")
async def maintenance_task_create(
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
        return HTMLResponse("Cannot add maintenance tasks to retired assets", status_code=400)

    raw_form = await request.form()
    try:
        data, component_ids = _clean_task_form(raw_form)
        create_task(db, asset_id, data, user, component_ids)
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request,
            "maintenance_tasks/form.html",
            _task_form_context(request, asset, None, user, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.get("/{task_id}/edit", response_class=HTMLResponse)
def maintenance_task_edit(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "maintenance_tasks/form.html",
        _task_form_context(request, asset, task, user),
    )


@router.post("/{task_id}/edit")
async def maintenance_task_update(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    raw_form = await request.form()
    try:
        data, component_ids = _clean_task_form(raw_form)
        update_task(db, task, data, component_ids)
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request,
            "maintenance_tasks/form.html",
            _task_form_context(request, asset, task, user, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{task_id}/pause")
def maintenance_task_pause(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return _set_status(request, asset_id, task_id, db, "paused")


@router.post("/{task_id}/resume")
def maintenance_task_resume(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    return _set_status(request, asset_id, task_id, db, "upcoming")


def _set_status(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session,
    status: str,
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    set_task_status(db, task, status)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{task_id}/delete")
def maintenance_task_delete(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    delete_task(db, task)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.get("/{task_id}/complete", response_class=HTMLResponse)
def maintenance_task_complete_form(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "service_records/form.html",
        {
            "asset": asset,
            "record": None,
            "completion_task": task,
            "cost_categories": COST_CATEGORIES,
            "today": date.today(),
            "user": user,
        },
    )


@router.post("/{task_id}/complete")
async def maintenance_task_complete(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    raw_form = await request.form()
    data = dict(raw_form)
    data.pop("csrf_token", None)
    try:
        component_ids = [uuid.UUID(v) for v in raw_form.getlist("component_ids")]
    except ValueError:
        return HTMLResponse("Invalid component id", status_code=400)
    data.pop("component_ids", None)
    documents_files: list[UploadFile] = [
        f for f in raw_form.getlist("documents") if getattr(f, "filename", "")
    ]
    data.pop("documents", None)
    data["is_diy"] = "is_diy" in data
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None
    if data.get("mileage_at_service"):
        data["mileage_at_service"] = int(data["mileage_at_service"].replace(",", ""))

    try:
        record = create_service_record(db, asset_id, data, user, component_ids)
        complete_task(db, task, record)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    await _save_attached_documents(db, asset_id, record.id, documents_files, user)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{task_id}/quick-complete")
def maintenance_task_quick_complete(
    request: Request,
    asset_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    task = get_task(db, task_id)
    if not asset or not task or task.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    record = create_service_record(
        db,
        asset_id,
        {
            "title": task.title,
            "service_date": date.today(),
            "cost_category": "maintenance",
            "cost": 0,
            "is_diy": True,
            "description": "Marked done from dashboard.",
        },
        user,
        [component.id for component in task.components],
    )
    complete_task(db, task, record)

    return RedirectResponse(url="/", status_code=303)


@router.get("/partials/list", response_class=HTMLResponse)
def maintenance_tasks_partial(
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
    active_component = next((c for c in asset.components if c.id == component), None)
    active_component_id = active_component.id if active_component else None
    tasks = list_tasks_for_asset(db, asset_id)
    if active_component_id:
        tasks = [t for t in tasks if any(c.id == active_component_id for c in t.components)]
    return request.app.state.templates.TemplateResponse(
        request,
        "assets/partials/maintenance_tasks_section.html",
        {
            "asset": asset,
            "maintenance_tasks": tasks,
            "computed_status": computed_status,
            "active_component": active_component,
        },
    )

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.database import get_db
from app.services.assets import get_asset
from app.services.components import (
    create_component,
    delete_component,
    get_component,
    get_preset_components,
    list_components,
)

router = APIRouter(prefix="/assets/{asset_id}/components", tags=["components"])


def _render_components_partial(
    request: Request, asset_id: uuid.UUID, db: Session
):
    asset = get_asset(db, asset_id)
    components = list_components(db, asset_id)
    preset_names = get_preset_components(asset.category) if asset else []
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/components_list.html",
        {
            "asset": asset,
            "components": components,
            "preset_names": preset_names,
        },
    )


@router.post("", response_class=HTMLResponse)
async def component_create(
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
    name = form.get("name", "").strip()
    if name:
        create_component(db, asset_id, {"name": name})
    return _render_components_partial(request, asset_id, db)


@router.post("/{component_id}/delete", response_class=HTMLResponse)
def component_delete(
    request: Request,
    asset_id: uuid.UUID,
    component_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    component = get_component(db, component_id)
    if component and component.asset_id == asset_id:
        delete_component(db, component)
    return _render_components_partial(request, asset_id, db)


@router.post("/preset", response_class=HTMLResponse)
async def component_preset(
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
    name = form.get("name", "").strip()
    if name:
        create_component(db, asset_id, {"name": name})
    return _render_components_partial(request, asset_id, db)

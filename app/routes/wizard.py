"""First-run wizard — guided 2–3 asset onboarding.

Shown once per user when they have no assets and haven't marked the
wizard as completed. Every step has a "Skip for now" escape hatch so
the user is never trapped.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.services.assets import CATEGORIES, create_asset, get_asset, save_photo
from app.services.components import create_component
from app.services.service_records import create_service_record

router = APIRouter(prefix="/wizard", tags=["wizard"])


def _mark_complete(db: Session, user) -> None:
    user.wizard_completed = True
    db.add(user)
    db.commit()


@router.get("", response_class=HTMLResponse)
def wizard_welcome(request: Request):
    user = get_current_user(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "wizard/step1_welcome.html",
        {"user": user, "step": 1, "total_steps": 3},
    )


@router.get("/asset", response_class=HTMLResponse)
def wizard_asset_form(request: Request):
    user = get_current_user(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "wizard/step2_asset.html",
        {
            "user": user,
            "categories": CATEGORIES,
            "step": 2,
            "total_steps": 3,
        },
    )


@router.post("/asset")
async def wizard_create_asset(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    form = await request.form()
    data = dict(form)

    photo_file: UploadFile | None = data.pop("photo", None)
    preset_components = data.pop("preset_components", None)

    # The same empty-string cleanup as the main asset form
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None

    if data.get("year"):
        data["year"] = int(data["year"])
    if data.get("purchase_price"):
        data["purchase_price"] = Decimal(data["purchase_price"])
    if data.get("current_mileage"):
        data["current_mileage"] = int(data["current_mileage"].replace(",", ""))

    asset = create_asset(db, data, user)

    if photo_file and hasattr(photo_file, "filename") and photo_file.filename:
        settings = get_settings()
        relative_path = await save_photo(asset.id, photo_file, settings.upload_dir)
        asset.photo = relative_path
        db.commit()

    # Auto-add any preset components the user chose to include
    if preset_components:
        selected = form.getlist("preset_components")
        for name in selected:
            if name.strip():
                create_component(db, asset.id, {"name": name.strip()})

    return RedirectResponse(url=f"/wizard/next/{asset.id}", status_code=303)


@router.get("/next/{asset_id}", response_class=HTMLResponse)
def wizard_next(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset or asset.created_by_id != user.id:
        return RedirectResponse("/wizard", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "wizard/step3_done.html",
        {
            "user": user,
            "asset": asset,
            "step": 3,
            "total_steps": 3,
        },
    )


@router.post("/service-record/{asset_id}")
async def wizard_create_service_record(
    request: Request,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    if not asset or asset.created_by_id != user.id:
        return RedirectResponse("/wizard", status_code=303)

    form = await request.form()
    data = dict(form)
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None
    if data.get("cost"):
        data["cost"] = Decimal(data["cost"])
    # service_date is NOT NULL on the model — default to today if blank
    if not data.get("service_date"):
        data["service_date"] = date.today()

    create_service_record(db, asset_id, data, user)
    _mark_complete(db, user)
    return RedirectResponse(url="/", status_code=303)


@router.post("/complete")
def wizard_complete(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    _mark_complete(db, user)
    return RedirectResponse(url="/", status_code=303)

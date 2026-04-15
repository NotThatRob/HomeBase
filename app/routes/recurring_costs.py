import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import check_asset_access, get_current_user
from app.database import get_db
from app.models.recurring_cost import RECURRING_COST_CATEGORIES, RECURRING_FREQUENCIES
from app.services.assets import get_asset
from app.services.recurring_costs import (
    annualize_amount,
    create_recurring_cost,
    delete_recurring_cost,
    get_recurring_cost,
    monthly_from_annual,
    update_recurring_cost,
)

router = APIRouter(prefix="/assets/{asset_id}/recurring-costs", tags=["recurring_costs"])


def _parse_form(raw: dict) -> dict:
    data = dict(raw)
    # Empty strings → None
    for key in list(data.keys()):
        if isinstance(data[key], str) and data[key].strip() == "":
            data[key] = None
    # Coerce amount
    if data.get("amount") is not None:
        try:
            data["amount"] = Decimal(str(data["amount"]).replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("Invalid amount") from exc
    # Coerce dates
    for field in ("start_date", "end_date"):
        value = data.get(field)
        if isinstance(value, str):
            try:
                data[field] = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError(f"Invalid {field}") from exc
    return data


def _form_context(
    asset,
    cost,
    user,
) -> dict:
    return {
        "asset": asset,
        "cost": cost,
        "frequencies": RECURRING_FREQUENCIES,
        "categories": RECURRING_COST_CATEGORIES,
        "today": date.today(),
        "user": user,
    }


@router.get("/new", response_class=HTMLResponse)
def recurring_cost_new(
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
        return HTMLResponse("Cannot add recurring costs to retired assets", status_code=400)
    return request.app.state.templates.TemplateResponse(
        request,
        "recurring_costs/form.html",
        _form_context(asset, None, user),
    )


@router.post("")
async def recurring_cost_create(
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
        return HTMLResponse("Cannot add recurring costs to retired assets", status_code=400)

    try:
        data = _parse_form(await request.form())
        create_recurring_cost(db, asset_id, data, user)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.get("/{cost_id}", response_class=HTMLResponse)
def recurring_cost_detail(
    request: Request,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    cost = get_recurring_cost(db, cost_id)
    if not asset or not cost or cost.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user)
    annual = annualize_amount(cost.amount, cost.frequency)
    return request.app.state.templates.TemplateResponse(
        request,
        "recurring_costs/detail.html",
        {
            "asset": asset,
            "cost": cost,
            "annual_cost": annual,
            "monthly_cost": monthly_from_annual(annual),
            "user": user,
        },
    )


@router.get("/{cost_id}/edit", response_class=HTMLResponse)
def recurring_cost_edit(
    request: Request,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    cost = get_recurring_cost(db, cost_id)
    if not asset or not cost or cost.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    return request.app.state.templates.TemplateResponse(
        request,
        "recurring_costs/form.html",
        _form_context(asset, cost, user),
    )


@router.post("/{cost_id}/edit")
async def recurring_cost_update(
    request: Request,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    cost = get_recurring_cost(db, cost_id)
    if not asset or not cost or cost.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)

    try:
        data = _parse_form(await request.form())
        update_recurring_cost(db, cost, data)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)


@router.post("/{cost_id}/delete")
def recurring_cost_delete(
    request: Request,
    asset_id: uuid.UUID,
    cost_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    user = get_current_user(request)
    asset = get_asset(db, asset_id)
    cost = get_recurring_cost(db, cost_id)
    if not asset or not cost or cost.asset_id != asset_id:
        return HTMLResponse("Not found", status_code=404)
    check_asset_access(asset, user, require_owner=True)
    delete_recurring_cost(db, cost)
    return RedirectResponse(url=f"/assets/{asset_id}", status_code=303)

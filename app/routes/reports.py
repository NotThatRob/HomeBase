import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.services.reports import (
    EXPORT_ENTITIES,
    ReportJSONEncoder,
    cost_by_year_chart,
    cost_per_asset_year,
    export_rows,
    full_backup,
    rows_to_csv,
    service_cost_by_category_chart,
    service_history_rows,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _csv_response(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_class=HTMLResponse)
def reports_index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    cost_rows = cost_per_asset_year(db, user)
    service_rows = service_history_rows(db, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "reports/index.html",
        {
            "user": user,
            "export_entities": sorted(EXPORT_ENTITIES),
            "cost_by_year_chart": cost_by_year_chart(cost_rows),
            "service_cost_by_category_chart": service_cost_by_category_chart(service_rows),
            "today": date.today(),
        },
    )


@router.get("/cost-by-asset-year", response_class=HTMLResponse)
def cost_by_asset_year_view(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    rows = cost_per_asset_year(db, user)
    total = sum((r["total"] for r in rows), Decimal("0"))
    return request.app.state.templates.TemplateResponse(
        request,
        "reports/cost_by_asset_year.html",
        {
            "user": user,
            "rows": rows,
            "grand_total": total,
            "today": date.today(),
        },
    )


@router.get("/cost-by-asset-year.csv")
def cost_by_asset_year_csv(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    rows = cost_per_asset_year(db, user)
    headers = ["asset_name", "year", "purchase", "service", "fuel", "total"]
    body = rows_to_csv(headers, rows)
    return _csv_response(body, "homebase-cost-by-asset-year.csv")


@router.get("/service-history", response_class=HTMLResponse)
def service_history_view(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    rows = service_history_rows(db, user)
    return request.app.state.templates.TemplateResponse(
        request,
        "reports/service_history.html",
        {
            "user": user,
            "rows": rows,
            "today": date.today(),
        },
    )


@router.get("/service-history.csv")
def service_history_csv(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    rows = service_history_rows(db, user)
    headers = [
        "service_date",
        "asset_name",
        "title",
        "vendor",
        "cost_category",
        "cost",
        "is_diy",
        "mileage_at_service",
        "description",
    ]
    body = rows_to_csv(headers, rows)
    return _csv_response(body, "homebase-service-history.csv")


@router.get("/exports/{entity}.csv")
def raw_entity_csv(request: Request, entity: str, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if entity not in EXPORT_ENTITIES:
        return Response("Unknown export", status_code=404)
    headers, rows = export_rows(db, user, entity)
    body = rows_to_csv(headers, rows)
    return _csv_response(body, f"homebase-{entity}.csv")


@router.get("/backup.json")
def backup_json(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    payload = full_backup(db, user)
    body = json.dumps(payload, cls=ReportJSONEncoder, indent=2)
    filename = f"homebase-backup-{date.today().isoformat()}.json"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

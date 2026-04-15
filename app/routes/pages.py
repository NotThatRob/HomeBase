import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.asset import Asset
from app.models.maintenance_task import TASK_PRIORITIES
from app.services import cost_service
from app.services.maintenance_tasks import (
    computed_status,
    dashboard_tasks,
    list_tasks_for_user,
)
from app.services.visibility import visible_asset_ids

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)

    # First-run: if the user has never completed the wizard and has no
    # assets of their own, route them through the guided onboarding flow.
    if not user.wizard_completed:
        own_asset_count = db.query(Asset).filter(Asset.created_by_id == user.id).count()
        if own_asset_count == 0:
            return RedirectResponse("/wizard", status_code=303)

    ownership = cost_service.get_household_ownership_summary(db, user)
    by_asset = cost_service.get_ownership_by_asset(db, user, limit=5)
    by_category = cost_service.get_actual_spend_by_category(db, user)
    spend_trend = cost_service.get_actual_spend_trend(db, user, months=12)
    activity = cost_service.get_recent_activity(db, user, limit=10)
    overdue_tasks, upcoming_tasks = dashboard_tasks(db, user, days_ahead=30)

    # Chart.js payloads — Decimals don't serialize to JSON, so cast to float
    # at the view boundary. Precision loss is irrelevant for a bar/donut chart.
    by_asset_chart = {
        "labels": [row["name"] for row in by_asset],
        "values": [float(row["total"]) for row in by_asset],
    }
    by_category_chart = {
        "labels": [row["category"].replace("_", " ").title() for row in by_category],
        "values": [float(row["total"]) for row in by_category],
    }
    spend_trend_chart = {
        "labels": [row["label"] for row in spend_trend],
        "service": [float(row["service"]) for row in spend_trend],
        "fuel": [float(row["fuel"]) for row in spend_trend],
        "total": [float(row["total"]) for row in spend_trend],
    }

    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "ownership": ownership,
            "by_asset": by_asset,
            "by_category": by_category,
            "by_asset_chart": by_asset_chart,
            "by_category_chart": by_category_chart,
            "spend_trend_chart": spend_trend_chart,
            "activity": activity,
            "overdue_tasks": overdue_tasks,
            "upcoming_tasks": upcoming_tasks,
            "computed_status": computed_status,
            "month_label": date.today().strftime("%B"),
        },
    )


@router.get("/maintenance", response_class=HTMLResponse)
def maintenance_index(
    request: Request,
    db: Session = Depends(get_db),
    asset: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
):
    user = get_current_user(request)

    asset_id: uuid.UUID | None = None
    if asset:
        try:
            asset_id = uuid.UUID(asset)
        except ValueError:
            asset_id = None

    valid_status = {"overdue", "due", "upcoming", "paused", "completed"}
    status_filter = status if status in valid_status else None
    priority_filter = priority if priority in TASK_PRIORITIES else None

    pairs = list_tasks_for_user(
        db,
        user,
        asset_id=asset_id,
        status_filter=status_filter,
        priority_filter=priority_filter,
    )

    groups: dict[str, list] = {
        "overdue": [],
        "due": [],
        "upcoming": [],
        "paused": [],
        "completed": [],
    }
    for task, bucket in pairs:
        groups.setdefault(bucket, []).append(task)

    # Bucket counts computed without filters applied, so the summary strip
    # reflects the whole household rather than the current filter view.
    all_pairs = list_tasks_for_user(db, user)
    counts = {"overdue": 0, "due": 0, "upcoming": 0, "paused": 0, "completed": 0}
    for _task, bucket in all_pairs:
        counts[bucket] = counts.get(bucket, 0) + 1

    visible_assets = (
        db.query(Asset)
        .filter(Asset.id.in_(visible_asset_ids(user)))
        .order_by(Asset.name.asc())
        .all()
    )

    return request.app.state.templates.TemplateResponse(
        request,
        "maintenance/index.html",
        {
            "user": user,
            "groups": groups,
            "counts": counts,
            "computed_status": computed_status,
            "visible_assets": visible_assets,
            "priorities": TASK_PRIORITIES,
            "filter_asset": asset or "",
            "filter_status": status_filter or "",
            "filter_priority": priority_filter or "",
            "any_tasks": bool(all_pairs),
            "today": date.today(),
        },
    )


@router.get("/partials/ping", response_class=HTMLResponse)
def ping_partial(request: Request):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return request.app.state.templates.TemplateResponse(
        request, "partials/ping.html", {"time": now}
    )

"""Dashboard aggregations over service records and documents.

Every query must respect the same visibility rule as ``list_assets``:
shared assets + the caller's own personal assets. Leaking a personal asset
into another user's totals would be a privacy bug, so all aggregation
goes through ``_visible_asset_ids``.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.document import Document
from app.models.fuel_log import FuelLog
from app.models.recurring_cost import RecurringCost
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.services.recurring_costs import annualize_amount, monthly_from_annual
from app.services.visibility import visible_asset_ids as _visible_asset_ids


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def get_spend_totals(db: Session, user: User) -> dict:
    """Return total service spend across month / year / all-time.

    Uses a single query with conditional sums so we hit the DB once.
    Month/year bounds are computed in Python so the SQL stays portable.
    """
    visible = _visible_asset_ids(user)
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    row = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (ServiceRecord.service_date >= month_start, ServiceRecord.cost),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (ServiceRecord.service_date >= year_start, ServiceRecord.cost),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(ServiceRecord.cost), 0),
        )
        .filter(ServiceRecord.asset_id.in_(visible))
        .one()
    )

    return {
        "month": _to_decimal(row[0]),
        "year": _to_decimal(row[1]),
        "all_time": _to_decimal(row[2]),
    }


def get_spend_by_asset(db: Session, user: User, limit: int = 5) -> list[dict]:
    """Top ``limit`` assets by total service spend, highest first.

    Zero-cost assets are excluded — they add noise to the bar chart
    without telling the user anything actionable.
    """
    visible = _visible_asset_ids(user)
    rows = (
        db.query(
            Asset.id,
            Asset.name,
            func.coalesce(func.sum(ServiceRecord.cost), 0).label("total"),
        )
        .join(ServiceRecord, ServiceRecord.asset_id == Asset.id)
        .filter(Asset.id.in_(visible))
        .group_by(Asset.id, Asset.name)
        .having(func.coalesce(func.sum(ServiceRecord.cost), 0) > 0)
        .order_by(func.sum(ServiceRecord.cost).desc())
        .limit(limit)
        .all()
    )
    return [{"id": row[0], "name": row[1], "total": _to_decimal(row[2])} for row in rows]


def get_spend_by_category(db: Session, user: User) -> list[dict]:
    """Spend grouped by cost_category, highest first."""
    visible = _visible_asset_ids(user)
    rows = (
        db.query(
            ServiceRecord.cost_category,
            func.coalesce(func.sum(ServiceRecord.cost), 0).label("total"),
        )
        .filter(ServiceRecord.asset_id.in_(visible))
        .group_by(ServiceRecord.cost_category)
        .having(func.coalesce(func.sum(ServiceRecord.cost), 0) > 0)
        .order_by(func.sum(ServiceRecord.cost).desc())
        .all()
    )
    return [{"category": row[0], "total": _to_decimal(row[1])} for row in rows]


def get_recent_activity(db: Session, user: User, limit: int = 10) -> list[dict]:
    """Most recent service records + document uploads across visible assets.

    Two focused queries merged in Python instead of a SQL ``UNION ALL`` —
    the schemas don't line up cleanly and the result set is tiny at our
    scale. Each query fetches ``limit`` rows so the merge has enough
    headroom even when one source dominates.
    """
    visible = _visible_asset_ids(user)

    records = (
        db.query(ServiceRecord)
        .options(
            joinedload(ServiceRecord.asset),
            joinedload(ServiceRecord.created_by),
        )
        .filter(ServiceRecord.asset_id.in_(visible))
        .order_by(ServiceRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    documents = (
        db.query(Document)
        .options(
            joinedload(Document.asset),
            joinedload(Document.uploaded_by),
        )
        .filter(Document.asset_id.in_(visible))
        .order_by(Document.uploaded_at.desc())
        .limit(limit)
        .all()
    )

    items: list[dict] = []
    for r in records:
        items.append(
            {
                "kind": "service",
                "title": r.title,
                "asset_name": r.asset.name,
                "asset_id": r.asset_id,
                "user_name": r.created_by.display_name if r.created_by else "",
                "when": _normalize_timestamp(r.created_at),
                "href": f"/assets/{r.asset_id}/service-records/{r.id}",
            }
        )
    for d in documents:
        items.append(
            {
                "kind": "document",
                "title": d.title,
                "asset_name": d.asset.name,
                "asset_id": d.asset_id,
                "user_name": d.uploaded_by.display_name if d.uploaded_by else "",
                "when": _normalize_timestamp(d.uploaded_at),
                "href": f"/documents/{d.id}",
            }
        )

    items.sort(key=lambda i: i["when"], reverse=True)
    return items[:limit]


def get_monthly_recurring_obligation(db: Session, user: User) -> Decimal:
    """Projected monthly cost of all currently-active recurring obligations.

    Active means ``end_date`` is null or in the future. One-time costs
    contribute zero by definition (they don't recur).
    """
    visible = _visible_asset_ids(user)
    today = date.today()
    rows = (
        db.query(RecurringCost.amount, RecurringCost.frequency)
        .filter(RecurringCost.asset_id.in_(visible))
        .filter(or_(RecurringCost.end_date.is_(None), RecurringCost.end_date >= today))
        .all()
    )
    annual = Decimal("0")
    for amount, frequency in rows:
        annual += annualize_amount(amount, frequency)
    return monthly_from_annual(annual)


def get_recurring_by_category(db: Session, user: User) -> list[dict]:
    """Active recurring obligations grouped by category, annualized."""
    visible = _visible_asset_ids(user)
    today = date.today()
    rows = (
        db.query(RecurringCost.cost_category, RecurringCost.amount, RecurringCost.frequency)
        .filter(RecurringCost.asset_id.in_(visible))
        .filter(or_(RecurringCost.end_date.is_(None), RecurringCost.end_date >= today))
        .all()
    )
    totals: dict[str, Decimal] = {}
    for category, amount, frequency in rows:
        totals[category] = totals.get(category, Decimal("0")) + annualize_amount(amount, frequency)
    return [
        {"category": cat, "total": total.quantize(Decimal("0.01"))}
        for cat, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        if total > 0
    ]


def get_fuel_spend_totals(db: Session, user: User) -> dict:
    """Fuel spend totals for visible vehicle assets."""
    visible = _visible_asset_ids(user)
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    row = (
        db.query(
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= month_start, FuelLog.total_cost), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= year_start, FuelLog.total_cost), else_=0)),
                0,
            ),
            func.coalesce(func.sum(FuelLog.total_cost), 0),
        )
        .filter(FuelLog.asset_id.in_(visible))
        .one()
    )
    return {
        "month": _to_decimal(row[0]),
        "year": _to_decimal(row[1]),
        "all_time": _to_decimal(row[2]),
    }


def get_household_ownership_summary(db: Session, user: User) -> dict:
    """Dashboard-level ownership totals for all visible assets.

    ``tracked_total`` is actual known ownership cost: purchase prices,
    service records, and fuel logs. Recurring costs are projected
    obligations, so they only contribute to the run-rate estimates.
    """
    visible = _visible_asset_ids(user)
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    cutoff = today - timedelta(days=365)

    purchase_total = _to_decimal(
        db.query(func.coalesce(func.sum(Asset.purchase_price), 0))
        .filter(Asset.id.in_(visible))
        .scalar()
    )
    service_row = (
        db.query(
            func.coalesce(
                func.sum(
                    case((ServiceRecord.service_date >= month_start, ServiceRecord.cost), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case((ServiceRecord.service_date >= year_start, ServiceRecord.cost), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(case((ServiceRecord.service_date >= cutoff, ServiceRecord.cost), else_=0)),
                0,
            ),
            func.coalesce(func.sum(ServiceRecord.cost), 0),
        )
        .filter(ServiceRecord.asset_id.in_(visible))
        .one()
    )
    fuel_row = (
        db.query(
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= month_start, FuelLog.total_cost), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= year_start, FuelLog.total_cost), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= cutoff, FuelLog.total_cost), else_=0)),
                0,
            ),
            func.coalesce(func.sum(FuelLog.total_cost), 0),
        )
        .filter(FuelLog.asset_id.in_(visible))
        .one()
    )

    annual_recurring = get_active_annual_recurring_obligation(db, user)
    service_month = _to_decimal(service_row[0])
    service_year = _to_decimal(service_row[1])
    service_last_12 = _to_decimal(service_row[2])
    service_total = _to_decimal(service_row[3])
    fuel_month = _to_decimal(fuel_row[0])
    fuel_year = _to_decimal(fuel_row[1])
    fuel_last_12 = _to_decimal(fuel_row[2])
    fuel_total = _to_decimal(fuel_row[3])

    last_12_actual = service_last_12 + fuel_last_12
    return {
        "month_actual": service_month + fuel_month,
        "year_actual": service_year + fuel_year,
        "purchase_total": purchase_total,
        "service_total": service_total,
        "fuel_total": fuel_total,
        "tracked_total": purchase_total + service_total + fuel_total,
        "last_12_actual": last_12_actual,
        "annual_recurring": annual_recurring,
        "monthly_recurring": monthly_from_annual(annual_recurring),
        "annual_run_rate": last_12_actual + annual_recurring,
    }


def get_active_annual_recurring_obligation(db: Session, user: User) -> Decimal:
    """Projected annual cost of currently-active recurring obligations."""
    visible = _visible_asset_ids(user)
    today = date.today()
    rows = (
        db.query(RecurringCost.amount, RecurringCost.frequency)
        .filter(RecurringCost.asset_id.in_(visible))
        .filter(or_(RecurringCost.end_date.is_(None), RecurringCost.end_date >= today))
        .all()
    )
    annual = Decimal("0")
    for amount, frequency in rows:
        annual += annualize_amount(amount, frequency)
    return annual.quantize(Decimal("0.01"))


def get_ownership_by_asset(db: Session, user: User, limit: int = 5) -> list[dict]:
    """Top visible assets by tracked ownership cost, highest first."""
    visible = _visible_asset_ids(user)
    assets = (
        db.query(Asset.id, Asset.name, Asset.purchase_price)
        .filter(Asset.id.in_(visible))
        .all()
    )
    service_rows = (
        db.query(
            ServiceRecord.asset_id,
            func.coalesce(func.sum(ServiceRecord.cost), 0).label("total"),
        )
        .filter(ServiceRecord.asset_id.in_(visible))
        .group_by(ServiceRecord.asset_id)
        .all()
    )
    fuel_rows = (
        db.query(FuelLog.asset_id, func.coalesce(func.sum(FuelLog.total_cost), 0).label("total"))
        .filter(FuelLog.asset_id.in_(visible))
        .group_by(FuelLog.asset_id)
        .all()
    )
    service_totals = {row[0]: _to_decimal(row[1]) for row in service_rows}
    fuel_totals = {row[0]: _to_decimal(row[1]) for row in fuel_rows}

    rows = []
    for asset_id, name, purchase_price in assets:
        total = (
            _to_decimal(purchase_price)
            + service_totals.get(asset_id, Decimal("0"))
            + fuel_totals.get(asset_id, Decimal("0"))
        )
        if total > 0:
            rows.append({"id": asset_id, "name": name, "total": total})
    rows.sort(key=lambda row: row["total"], reverse=True)
    return rows[:limit]


def get_actual_spend_by_category(db: Session, user: User) -> list[dict]:
    """Actual service + fuel spend grouped by category, highest first."""
    visible = _visible_asset_ids(user)
    rows = get_spend_by_category(db, user)
    totals = {row["category"]: row["total"] for row in rows}
    fuel_total = _to_decimal(
        db.query(func.coalesce(func.sum(FuelLog.total_cost), 0))
        .filter(FuelLog.asset_id.in_(visible))
        .scalar()
    )
    if fuel_total > 0:
        totals["fuel"] = totals.get("fuel", Decimal("0")) + fuel_total
    return [
        {"category": category, "total": total}
        for category, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        if total > 0
    ]


def get_actual_spend_trend(db: Session, user: User, months: int = 12) -> list[dict]:
    """Monthly actual service + fuel spend for the trailing ``months`` months."""
    visible = _visible_asset_ids(user)
    current_month = date.today().replace(day=1)
    first_month = _add_months(current_month, -(months - 1))
    buckets = {
        _add_months(first_month, offset): {"service": Decimal("0"), "fuel": Decimal("0")}
        for offset in range(months)
    }

    service_rows = (
        db.query(ServiceRecord.service_date, ServiceRecord.cost)
        .filter(ServiceRecord.asset_id.in_(visible))
        .filter(ServiceRecord.service_date >= first_month)
        .all()
    )
    fuel_rows = (
        db.query(FuelLog.fillup_date, FuelLog.total_cost)
        .filter(FuelLog.asset_id.in_(visible))
        .filter(FuelLog.fillup_date >= first_month)
        .all()
    )
    for service_date, cost in service_rows:
        bucket = service_date.replace(day=1)
        if bucket in buckets:
            buckets[bucket]["service"] += _to_decimal(cost)
    for fillup_date, total_cost in fuel_rows:
        bucket = fillup_date.replace(day=1)
        if bucket in buckets:
            buckets[bucket]["fuel"] += _to_decimal(total_cost)

    return [
        {
            "month": month,
            "label": month.strftime("%b %Y"),
            "service": totals["service"].quantize(Decimal("0.01")),
            "fuel": totals["fuel"].quantize(Decimal("0.01")),
            "total": (totals["service"] + totals["fuel"]).quantize(Decimal("0.01")),
        }
        for month, totals in sorted(buckets.items())
    ]


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=1)


def get_asset_actual_spend_trend(db: Session, asset_id, months: int = 12) -> list[dict]:
    """Monthly actual service + fuel spend for one asset.

    Callers MUST authorize the asset (e.g., via ``check_asset_access``)
    before invoking — this helper trusts ``asset_id`` and does no visibility check.
    """
    current_month = date.today().replace(day=1)
    first_month = _add_months(current_month, -(months - 1))
    buckets = {
        _add_months(first_month, offset): {"service": Decimal("0"), "fuel": Decimal("0")}
        for offset in range(months)
    }

    service_rows = (
        db.query(ServiceRecord.service_date, ServiceRecord.cost)
        .filter(ServiceRecord.asset_id == asset_id)
        .filter(ServiceRecord.service_date >= first_month)
        .all()
    )
    fuel_rows = (
        db.query(FuelLog.fillup_date, FuelLog.total_cost)
        .filter(FuelLog.asset_id == asset_id)
        .filter(FuelLog.fillup_date >= first_month)
        .all()
    )
    for service_date, cost in service_rows:
        bucket = service_date.replace(day=1)
        if bucket in buckets:
            buckets[bucket]["service"] += _to_decimal(cost)
    for fillup_date, total_cost in fuel_rows:
        bucket = fillup_date.replace(day=1)
        if bucket in buckets:
            buckets[bucket]["fuel"] += _to_decimal(total_cost)

    return [
        {
            "month": month,
            "label": month.strftime("%b %Y"),
            "service": totals["service"].quantize(Decimal("0.01")),
            "fuel": totals["fuel"].quantize(Decimal("0.01")),
            "total": (totals["service"] + totals["fuel"]).quantize(Decimal("0.01")),
        }
        for month, totals in sorted(buckets.items())
    ]


def get_asset_cost_composition(db: Session, asset_id) -> dict:
    """Chart-friendly ownership composition for one asset.

    Callers MUST authorize the asset (e.g., via ``check_asset_access``)
    before invoking — this helper trusts ``asset_id`` and does no visibility check.
    """
    summary = get_asset_ownership_summary(db, asset_id)
    return {
        "purchase_price": summary["purchase_price"],
        "service_total": summary["service_total"],
        "fuel_total": summary["fuel_total"],
        "annual_recurring": summary["annual_recurring"],
    }


def get_asset_ownership_summary(db: Session, asset_id) -> dict:
    """Ownership cost summary for a single asset.

    ``tracked_total`` is actual known spend only. Recurring costs are projected
    obligations and are surfaced separately plus in the annual run-rate estimate.

    Callers MUST authorize the asset (e.g., via ``check_asset_access``)
    before invoking — this helper trusts ``asset_id`` and does no visibility check.
    """
    asset = db.get(Asset, asset_id)
    purchase_price = _to_decimal(asset.purchase_price if asset else None)
    cutoff = date.today() - timedelta(days=365)
    today = date.today()

    service_row = (
        db.query(
            func.coalesce(func.sum(ServiceRecord.cost), 0),
            func.coalesce(
                func.sum(case((ServiceRecord.service_date >= cutoff, ServiceRecord.cost), else_=0)),
                0,
            ),
        )
        .filter(ServiceRecord.asset_id == asset_id)
        .one()
    )
    fuel_row = (
        db.query(
            func.coalesce(func.sum(FuelLog.total_cost), 0),
            func.coalesce(
                func.sum(case((FuelLog.fillup_date >= cutoff, FuelLog.total_cost), else_=0)),
                0,
            ),
        )
        .filter(FuelLog.asset_id == asset_id)
        .one()
    )
    recurring_rows = (
        db.query(RecurringCost.amount, RecurringCost.frequency)
        .filter(RecurringCost.asset_id == asset_id)
        .filter(or_(RecurringCost.end_date.is_(None), RecurringCost.end_date >= today))
        .all()
    )

    service_total = _to_decimal(service_row[0])
    service_last_12_months = _to_decimal(service_row[1])
    fuel_total = _to_decimal(fuel_row[0])
    fuel_last_12_months = _to_decimal(fuel_row[1])
    annual_recurring = sum(
        (annualize_amount(amount, frequency) for amount, frequency in recurring_rows),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    monthly_recurring = monthly_from_annual(annual_recurring)
    tracked_total = purchase_price + service_total + fuel_total
    annual_run_rate = service_last_12_months + fuel_last_12_months + annual_recurring
    per_mile = _vehicle_per_mile_metrics(
        db,
        asset,
        asset_id,
        tracked_total,
        fuel_total,
        annual_run_rate,
        cutoff,
    )

    return {
        "purchase_price": purchase_price,
        "service_total": service_total,
        "fuel_total": fuel_total,
        "monthly_recurring": monthly_recurring,
        "annual_recurring": annual_recurring,
        "tracked_total": tracked_total,
        "annual_run_rate": annual_run_rate,
        "service_last_12_months": service_last_12_months,
        "fuel_last_12_months": fuel_last_12_months,
        **per_mile,
    }


def _vehicle_per_mile_metrics(
    db: Session,
    asset: Asset | None,
    asset_id,
    tracked_total: Decimal,
    fuel_total: Decimal,
    annual_run_rate: Decimal,
    cutoff: date,
) -> dict:
    metrics = {
        "tracked_cost_per_mile": None,
        "fuel_cost_per_mile": None,
        "operating_cost_per_mile": None,
        "observed_fuel_miles": None,
        "estimated_annual_miles": None,
        "per_mile_available": False,
    }
    if not asset or asset.category != "vehicle":
        return metrics

    current_mileage = (
        asset.vehicle_meta.current_mileage
        if asset.vehicle_meta and asset.vehicle_meta.current_mileage
        else None
    )
    if current_mileage and current_mileage > 0:
        metrics["tracked_cost_per_mile"] = _money_per_mile(tracked_total, Decimal(current_mileage))

    fuel_cost_per_mile = _fuel_cost_per_mile(db, asset_id)
    metrics["fuel_cost_per_mile"] = fuel_cost_per_mile["cost_per_mile"]
    metrics["observed_fuel_miles"] = fuel_cost_per_mile["observed_miles"]

    annual_miles = _estimate_annual_miles(db, asset_id, cutoff)
    if annual_miles:
        metrics["estimated_annual_miles"] = annual_miles.quantize(Decimal("1"))
        metrics["operating_cost_per_mile"] = _money_per_mile(annual_run_rate, annual_miles)

    metrics["per_mile_available"] = any(
        metrics[key] is not None
        for key in (
            "tracked_cost_per_mile",
            "fuel_cost_per_mile",
            "operating_cost_per_mile",
        )
    )
    return metrics


def _fuel_cost_per_mile(db: Session, asset_id) -> dict:
    rows = (
        db.query(FuelLog.total_cost, FuelLog.mileage_at_fillup)
        .filter(FuelLog.asset_id == asset_id)
        .filter(FuelLog.gallons.is_not(None))
        .filter(FuelLog.mileage_at_fillup.is_not(None))
        .all()
    )
    if len(rows) < 2:
        return {"cost_per_mile": None, "observed_miles": None}

    mileages = [row[1] for row in rows]
    observed_miles = max(mileages) - min(mileages)
    if observed_miles <= 0:
        return {"cost_per_mile": None, "observed_miles": None}

    fuel_total = sum((_to_decimal(row[0]) for row in rows), Decimal("0"))
    return {
        "cost_per_mile": _money_per_mile(fuel_total, Decimal(observed_miles)),
        "observed_miles": observed_miles,
    }


def _estimate_annual_miles(db: Session, asset_id, cutoff: date) -> Decimal | None:
    points = []
    fuel_points = (
        db.query(FuelLog.fillup_date, FuelLog.mileage_at_fillup)
        .filter(FuelLog.asset_id == asset_id)
        .filter(FuelLog.fillup_date >= cutoff)
        .filter(FuelLog.mileage_at_fillup.is_not(None))
        .all()
    )
    service_points = (
        db.query(ServiceRecord.service_date, ServiceRecord.mileage_at_service)
        .filter(ServiceRecord.asset_id == asset_id)
        .filter(ServiceRecord.service_date >= cutoff)
        .filter(ServiceRecord.mileage_at_service.is_not(None))
        .all()
    )
    points.extend((row[0], row[1]) for row in fuel_points)
    points.extend((row[0], row[1]) for row in service_points)
    if len(points) < 2:
        return None

    points.sort(key=lambda point: (point[0], point[1]))
    first_date, first_mileage = points[0]
    last_date, last_mileage = points[-1]
    day_delta = (last_date - first_date).days
    mile_delta = last_mileage - first_mileage
    if day_delta <= 0 or mile_delta <= 0:
        return None
    return (Decimal(mile_delta) / Decimal(day_delta)) * Decimal("365")


def _money_per_mile(amount: Decimal, miles: Decimal) -> Decimal | None:
    if miles <= 0:
        return None
    return (amount / miles).quantize(Decimal("0.01"))


def _normalize_timestamp(value) -> datetime:
    """Ensure the sort key is a comparable datetime, not None."""
    if isinstance(value, datetime):
        return value
    return datetime.min

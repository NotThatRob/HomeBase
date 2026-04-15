"""Report aggregations and export helpers.

Kept separate from ``cost_service`` because reports return row-level export
shapes with their own column contracts — merging them with the dashboard's
pre-aggregated Decimals would tangle two different output formats.

Every query here MUST route through ``visible_asset_ids`` so that a user
cannot accidentally export another user's personal-visibility assets or
any rows attached to them.
"""

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.document import Document
from app.models.fuel_log import FuelLog
from app.models.maintenance_task import MaintenanceTask
from app.models.recurring_cost import RecurringCost
from app.models.service_record import ServiceRecord
from app.models.user import User
from app.services.visibility import visible_asset_ids

EXPORT_ENTITIES = {
    "assets",
    "service_records",
    "fuel_logs",
    "recurring_costs",
    "maintenance_tasks",
    "documents",
}


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Canned reports
# ---------------------------------------------------------------------------


def cost_per_asset_year(db: Session, user: User) -> list[dict]:
    """Per-asset, per-year ownership costs.

    Purchase cost is attributed to the purchase year for that asset;
    service and fuel roll up by their record date. Years with zero total
    for an asset are omitted to keep the table tight.
    """
    visible = visible_asset_ids(user)
    assets = db.query(Asset).filter(Asset.id.in_(visible)).order_by(Asset.name.asc()).all()
    service_rows = (
        db.query(ServiceRecord.asset_id, ServiceRecord.service_date, ServiceRecord.cost)
        .filter(ServiceRecord.asset_id.in_(visible))
        .all()
    )
    fuel_rows = (
        db.query(FuelLog.asset_id, FuelLog.fillup_date, FuelLog.total_cost)
        .filter(FuelLog.asset_id.in_(visible))
        .all()
    )

    # (asset_id, year) -> {"service": Decimal, "fuel": Decimal, "purchase": Decimal}
    buckets: dict[tuple[uuid.UUID, int], dict[str, Decimal]] = {}

    def bucket(asset_id: uuid.UUID, year: int) -> dict[str, Decimal]:
        key = (asset_id, year)
        if key not in buckets:
            buckets[key] = {
                "service": Decimal("0"),
                "fuel": Decimal("0"),
                "purchase": Decimal("0"),
            }
        return buckets[key]

    for asset in assets:
        if asset.purchase_date and asset.purchase_price:
            bucket(asset.id, asset.purchase_date.year)["purchase"] = _to_decimal(
                asset.purchase_price
            )
    for asset_id, service_date, cost in service_rows:
        bucket(asset_id, service_date.year)["service"] += _to_decimal(cost)
    for asset_id, fillup_date, total_cost in fuel_rows:
        bucket(asset_id, fillup_date.year)["fuel"] += _to_decimal(total_cost)

    name_by_id = {asset.id: asset.name for asset in assets}

    rows: list[dict] = []
    for (asset_id, year), totals in buckets.items():
        total = totals["purchase"] + totals["service"] + totals["fuel"]
        if total == 0:
            continue
        rows.append(
            {
                "asset_id": str(asset_id),
                "asset_name": name_by_id.get(asset_id, ""),
                "year": year,
                "purchase": totals["purchase"].quantize(Decimal("0.01")),
                "service": totals["service"].quantize(Decimal("0.01")),
                "fuel": totals["fuel"].quantize(Decimal("0.01")),
                "total": total.quantize(Decimal("0.01")),
            }
        )
    rows.sort(key=lambda r: (r["asset_name"].lower(), r["year"]))
    return rows


def service_history_rows(db: Session, user: User) -> list[dict]:
    """Flat chronological service log across every visible asset."""
    visible = visible_asset_ids(user)
    records = (
        db.query(ServiceRecord)
        .options(joinedload(ServiceRecord.asset))
        .filter(ServiceRecord.asset_id.in_(visible))
        .order_by(ServiceRecord.service_date.desc(), ServiceRecord.created_at.desc())
        .all()
    )
    return [
        {
            "service_date": r.service_date,
            "asset_name": r.asset.name if r.asset else "",
            "title": r.title,
            "vendor": r.vendor or "",
            "cost_category": r.cost_category,
            "cost": _to_decimal(r.cost).quantize(Decimal("0.01")),
            "is_diy": bool(r.is_diy),
            "mileage_at_service": r.mileage_at_service,
            "description": r.description or "",
        }
        for r in records
    ]


def cost_by_year_chart(rows: list[dict]) -> dict:
    """Stacked Chart.js payload for purchase, service, and fuel by year."""
    buckets: dict[int, dict[str, Decimal]] = {}
    for row in rows:
        year = int(row["year"])
        if year not in buckets:
            buckets[year] = {
                "purchase": Decimal("0"),
                "service": Decimal("0"),
                "fuel": Decimal("0"),
            }
        buckets[year]["purchase"] += _to_decimal(row["purchase"])
        buckets[year]["service"] += _to_decimal(row["service"])
        buckets[year]["fuel"] += _to_decimal(row["fuel"])

    years = sorted(buckets)
    return {
        "labels": [str(year) for year in years],
        "purchase": [float(buckets[year]["purchase"]) for year in years],
        "service": [float(buckets[year]["service"]) for year in years],
        "fuel": [float(buckets[year]["fuel"]) for year in years],
    }


def service_cost_by_category_chart(rows: list[dict]) -> dict:
    """Chart.js payload for service cost grouped by category."""
    buckets: dict[str, Decimal] = {}
    for row in rows:
        category = str(row["cost_category"] or "other")
        buckets[category] = buckets.get(category, Decimal("0")) + _to_decimal(row["cost"])

    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))
    return {
        "labels": [category.replace("_", " ").title() for category, _total in ordered],
        "values": [float(total) for _category, total in ordered],
    }


# ---------------------------------------------------------------------------
# Raw per-entity exports
# ---------------------------------------------------------------------------


def export_rows(db: Session, user: User, entity: str) -> tuple[list[str], list[dict]]:
    """Return (header_columns, rows) for a whitelisted entity."""
    if entity not in EXPORT_ENTITIES:
        raise ValueError(f"Unknown entity: {entity}")
    visible = visible_asset_ids(user)

    if entity == "assets":
        rows = db.query(Asset).filter(Asset.id.in_(visible)).order_by(Asset.name.asc()).all()
        headers = [
            "id",
            "name",
            "category",
            "subcategory",
            "make",
            "model",
            "year",
            "serial_number",
            "purchase_date",
            "purchase_price",
            "purchase_vendor",
            "warranty_expiration",
            "location",
            "status",
            "visibility",
            "notes",
            "created_at",
        ]
        data = [
            {
                "id": a.id,
                "name": a.name,
                "category": a.category,
                "subcategory": a.subcategory,
                "make": a.make,
                "model": a.model_name,
                "year": a.year,
                "serial_number": a.serial_number,
                "purchase_date": a.purchase_date,
                "purchase_price": a.purchase_price,
                "purchase_vendor": a.purchase_vendor,
                "warranty_expiration": a.warranty_expiration,
                "location": a.location,
                "status": a.status,
                "visibility": a.visibility,
                "notes": a.notes,
                "created_at": a.created_at,
            }
            for a in rows
        ]
        return headers, data

    if entity == "service_records":
        rows = (
            db.query(ServiceRecord)
            .options(joinedload(ServiceRecord.asset))
            .filter(ServiceRecord.asset_id.in_(visible))
            .order_by(ServiceRecord.service_date.desc())
            .all()
        )
        headers = [
            "id",
            "asset_id",
            "asset_name",
            "service_date",
            "title",
            "description",
            "vendor",
            "cost",
            "cost_category",
            "mileage_at_service",
            "is_diy",
            "next_service_notes",
            "created_at",
        ]
        data = [
            {
                "id": r.id,
                "asset_id": r.asset_id,
                "asset_name": r.asset.name if r.asset else "",
                "service_date": r.service_date,
                "title": r.title,
                "description": r.description,
                "vendor": r.vendor,
                "cost": r.cost,
                "cost_category": r.cost_category,
                "mileage_at_service": r.mileage_at_service,
                "is_diy": r.is_diy,
                "next_service_notes": r.next_service_notes,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return headers, data

    if entity == "fuel_logs":
        rows = (
            db.query(FuelLog)
            .options(joinedload(FuelLog.asset))
            .filter(FuelLog.asset_id.in_(visible))
            .order_by(FuelLog.fillup_date.desc())
            .all()
        )
        headers = [
            "id",
            "asset_id",
            "asset_name",
            "fillup_date",
            "gallons",
            "cost_per_gallon",
            "total_cost",
            "mileage_at_fillup",
            "full_tank",
            "station",
            "notes",
            "created_at",
        ]
        data = [
            {
                "id": f.id,
                "asset_id": f.asset_id,
                "asset_name": f.asset.name if f.asset else "",
                "fillup_date": f.fillup_date,
                "gallons": f.gallons,
                "cost_per_gallon": f.cost_per_gallon,
                "total_cost": f.total_cost,
                "mileage_at_fillup": f.mileage_at_fillup,
                "full_tank": f.full_tank,
                "station": f.station,
                "notes": f.notes,
                "created_at": f.created_at,
            }
            for f in rows
        ]
        return headers, data

    if entity == "recurring_costs":
        rows = (
            db.query(RecurringCost)
            .options(joinedload(RecurringCost.asset))
            .filter(RecurringCost.asset_id.in_(visible))
            .order_by(RecurringCost.start_date.desc())
            .all()
        )
        headers = [
            "id",
            "asset_id",
            "asset_name",
            "name",
            "amount",
            "frequency",
            "cost_category",
            "start_date",
            "end_date",
            "notes",
            "created_at",
        ]
        data = [
            {
                "id": r.id,
                "asset_id": r.asset_id,
                "asset_name": r.asset.name if r.asset else "",
                "name": r.name,
                "amount": r.amount,
                "frequency": r.frequency,
                "cost_category": r.cost_category,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "notes": r.notes,
                "created_at": r.created_at,
            }
            for r in rows
        ]
        return headers, data

    if entity == "maintenance_tasks":
        rows = (
            db.query(MaintenanceTask)
            .options(joinedload(MaintenanceTask.asset))
            .filter(MaintenanceTask.asset_id.in_(visible))
            .order_by(MaintenanceTask.next_due.asc().nullslast())
            .all()
        )
        headers = [
            "id",
            "asset_id",
            "asset_name",
            "title",
            "description",
            "schedule_type",
            "interval_value",
            "interval_unit",
            "calendar_month",
            "calendar_day",
            "usage_trigger_label",
            "usage_trigger_value",
            "next_due",
            "next_due_usage_value",
            "priority",
            "status",
            "created_at",
        ]
        data = [
            {
                "id": t.id,
                "asset_id": t.asset_id,
                "asset_name": t.asset.name if t.asset else "",
                "title": t.title,
                "description": t.description,
                "schedule_type": t.schedule_type,
                "interval_value": t.interval_value,
                "interval_unit": t.interval_unit,
                "calendar_month": t.calendar_month,
                "calendar_day": t.calendar_day,
                "usage_trigger_label": t.usage_trigger_label,
                "usage_trigger_value": t.usage_trigger_value,
                "next_due": t.next_due,
                "next_due_usage_value": t.next_due_usage_value,
                "priority": t.priority,
                "status": t.status,
                "created_at": t.created_at,
            }
            for t in rows
        ]
        return headers, data

    if entity == "documents":
        # Metadata only — never export file bytes.
        rows = (
            db.query(Document)
            .options(joinedload(Document.asset))
            .filter(Document.asset_id.in_(visible))
            .order_by(Document.uploaded_at.desc())
            .all()
        )
        headers = [
            "id",
            "asset_id",
            "asset_name",
            "service_record_id",
            "title",
            "doc_type",
            "file_name",
            "mime_type",
            "file_size",
            "notes",
            "uploaded_at",
        ]
        data = [
            {
                "id": d.id,
                "asset_id": d.asset_id,
                "asset_name": d.asset.name if d.asset else "",
                "service_record_id": d.service_record_id,
                "title": d.title,
                "doc_type": d.doc_type,
                "file_name": d.file_name,
                "mime_type": d.mime_type,
                "file_size": d.file_size,
                "notes": d.notes,
                "uploaded_at": d.uploaded_at,
            }
            for d in rows
        ]
        return headers, data

    raise ValueError(f"Unhandled entity: {entity}")


def full_backup(db: Session, user: User) -> dict[str, Any]:
    """Bundle every per-entity export into one JSON-serializable payload."""
    payload: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "exported_by": {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
        },
    }
    for entity in sorted(EXPORT_ENTITIES):
        _headers, rows = export_rows(db, user, entity)
        payload[entity] = rows
    return payload


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def rows_to_csv(headers: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: _csv_cell(row.get(h)) for h in headers})
    return buf.getvalue()


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


class ReportJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)

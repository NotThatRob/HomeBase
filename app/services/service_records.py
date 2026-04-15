import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.component import Component
from app.models.service_record import COST_CATEGORIES, ServiceRecord
from app.models.user import User
from app.services.validation import (
    MAX_MILEAGE,
    ensure_date_in_range,
    ensure_long_text,
    ensure_nonnegative_int,
    ensure_positive_money,
    ensure_short_text,
)

SERVICE_RECORD_ALLOWED_FIELDS = {
    "title", "description", "service_date", "vendor", "cost",
    "cost_category", "mileage_at_service", "is_diy", "next_service_notes",
}


def _filter_allowed(data: dict, allowed: set) -> dict:
    """Return only the keys present in the allowed set."""
    return {k: v for k, v in data.items() if k in allowed}


def _coerce_fields(data: dict) -> None:
    value = data.get("cost")
    if value is not None and not isinstance(value, Decimal):
        try:
            data["cost"] = Decimal(str(value).replace(",", "").strip())
        except InvalidOperation as exc:
            raise ValueError("Cost must be a number") from exc

    svc_date = data.get("service_date")
    if svc_date is not None and not isinstance(svc_date, date):
        try:
            data["service_date"] = datetime.strptime(str(svc_date), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Invalid service date") from exc


def _validate(data: dict) -> None:
    ensure_short_text(data.get("title"), "Title")
    ensure_short_text(data.get("vendor"), "Vendor")
    ensure_long_text(data.get("description"), "Description")
    ensure_long_text(data.get("next_service_notes"), "Next service notes")
    if data.get("service_date") is not None:
        ensure_date_in_range(data["service_date"], "Service date", max_years_ahead=5)
    if data.get("cost") is not None:
        ensure_positive_money(data["cost"], "Cost", allow_zero=True)
    if data.get("mileage_at_service") is not None:
        ensure_nonnegative_int(
            data["mileage_at_service"], "Mileage at service", upper=MAX_MILEAGE
        )
    cost_category = data.get("cost_category")
    if cost_category is not None and cost_category not in COST_CATEGORIES:
        raise ValueError(f"Invalid cost category: {cost_category!r}")


def list_service_records(
    db: Session, asset_id: uuid.UUID
) -> list[ServiceRecord]:
    return (
        db.query(ServiceRecord)
        .options(
            joinedload(ServiceRecord.components),
            joinedload(ServiceRecord.created_by),
        )
        .filter(ServiceRecord.asset_id == asset_id)
        .order_by(ServiceRecord.service_date.desc())
        .all()
    )


def get_service_record(
    db: Session, record_id: uuid.UUID
) -> ServiceRecord | None:
    return (
        db.query(ServiceRecord)
        .options(
            joinedload(ServiceRecord.components),
            joinedload(ServiceRecord.created_by),
        )
        .filter(ServiceRecord.id == record_id)
        .first()
    )


def create_service_record(
    db: Session,
    asset_id: uuid.UUID,
    data: dict,
    user: User,
    component_ids: list[uuid.UUID] | None = None,
) -> ServiceRecord:
    filtered = _filter_allowed(data, SERVICE_RECORD_ALLOWED_FIELDS)
    _coerce_fields(filtered)
    _validate(filtered)
    record = ServiceRecord(asset_id=asset_id, created_by_id=user.id, **filtered)

    if component_ids:
        components = (
            db.query(Component)
            .filter(Component.id.in_(component_ids))
            .filter(Component.asset_id == asset_id)
            .all()
        )
        if len(components) != len(set(component_ids)):
            raise ValueError("Component does not belong to this asset")
        record.components = components

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_service_record(
    db: Session,
    record: ServiceRecord,
    data: dict,
    component_ids: list[uuid.UUID] | None = None,
) -> ServiceRecord:
    filtered = _filter_allowed(data, SERVICE_RECORD_ALLOWED_FIELDS)
    _coerce_fields(filtered)
    _validate(filtered)
    for key, value in filtered.items():
        setattr(record, key, value)

    if component_ids is not None:
        components = (
            db.query(Component)
            .filter(Component.id.in_(component_ids))
            .filter(Component.asset_id == record.asset_id)
            .all()
        )
        if len(components) != len(set(component_ids)):
            raise ValueError("Component does not belong to this asset")
        record.components = components

    db.commit()
    db.refresh(record)
    return record


def delete_service_record(db: Session, record: ServiceRecord) -> None:
    db.delete(record)
    db.commit()


def get_service_summary(db: Session, asset_id: uuid.UUID) -> dict:
    result = (
        db.query(
            func.coalesce(func.sum(ServiceRecord.cost), 0),
            func.count(ServiceRecord.id),
            func.max(ServiceRecord.service_date),
        )
        .filter(ServiceRecord.asset_id == asset_id)
        .one()
    )
    return {
        "total_cost": Decimal(str(result[0])),
        "record_count": result[1],
        "last_service_date": result[2],
    }

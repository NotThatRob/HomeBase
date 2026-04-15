import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session, joinedload

from app.models.asset import Asset
from app.models.fuel_log import FuelLog
from app.models.user import User
from app.models.vehicle_meta import VehicleMeta
from app.services.validation import (
    MAX_GALLONS,
    MAX_MILEAGE,
    MAX_PRICE_PER_GALLON,
    ensure_long_text,
    ensure_money_upper,
    ensure_nonnegative_int,
    ensure_short_text,
)

FUEL_LOG_ALLOWED_FIELDS = {
    "fillup_date",
    "gallons",
    "cost_per_gallon",
    "total_cost",
    "mileage_at_fillup",
    "full_tank",
    "station",
    "notes",
}


def _filter_allowed(data: dict, allowed: set) -> dict:
    return {k: v for k, v in data.items() if k in allowed}


def list_fuel_logs(db: Session, asset_id: uuid.UUID) -> list[FuelLog]:
    return (
        db.query(FuelLog)
        .options(joinedload(FuelLog.created_by))
        .filter(FuelLog.asset_id == asset_id)
        .order_by(FuelLog.fillup_date.desc(), FuelLog.created_at.desc())
        .all()
    )


def get_fuel_log(db: Session, log_id: uuid.UUID) -> FuelLog | None:
    return (
        db.query(FuelLog)
        .options(joinedload(FuelLog.created_by))
        .filter(FuelLog.id == log_id)
        .first()
    )


def create_fuel_log(db: Session, asset: Asset, data: dict, user: User) -> FuelLog:
    filtered = _filter_allowed(data, FUEL_LOG_ALLOWED_FIELDS)
    _normalize_money_fields(filtered)
    _validate(asset, filtered)
    log = FuelLog(asset_id=asset.id, created_by_id=user.id, **filtered)
    db.add(log)
    if log.mileage_at_fillup is not None:
        _maybe_update_vehicle_mileage(db, asset, log.mileage_at_fillup)
    db.commit()
    db.refresh(log)
    return log


def update_fuel_log(db: Session, asset: Asset, log: FuelLog, data: dict) -> FuelLog:
    filtered = _filter_allowed(data, FUEL_LOG_ALLOWED_FIELDS)
    _normalize_money_fields(filtered)
    _validate(asset, filtered)
    for key, value in filtered.items():
        setattr(log, key, value)
    if log.mileage_at_fillup is not None:
        _maybe_update_vehicle_mileage(db, asset, log.mileage_at_fillup)
    db.commit()
    db.refresh(log)
    return log


def delete_fuel_log(db: Session, log: FuelLog) -> None:
    db.delete(log)
    db.commit()


def calculate_mpg(logs: list[FuelLog]) -> dict[uuid.UUID, Decimal]:
    """Return MPG by log id for full-tank intervals.

    Logs can be supplied in any order. Partial fillups are ignored as anchors
    and do not produce an MPG value.
    """
    mpg_by_id: dict[uuid.UUID, Decimal] = {}
    previous_full: FuelLog | None = None
    ordered = sorted(logs, key=lambda log: (log.fillup_date, log.created_at))
    for log in ordered:
        if not log.full_tank or log.mileage_at_fillup is None or not log.gallons:
            continue
        if (
            previous_full
            and previous_full.mileage_at_fillup is not None
            and log.mileage_at_fillup > previous_full.mileage_at_fillup
        ):
            miles = Decimal(log.mileage_at_fillup - previous_full.mileage_at_fillup)
            mpg_by_id[log.id] = (miles / Decimal(str(log.gallons))).quantize(Decimal("0.1"))
        previous_full = log
    return mpg_by_id


def get_fuel_summary(db: Session, asset_id: uuid.UUID) -> dict:
    logs = (
        db.query(FuelLog)
        .filter(FuelLog.asset_id == asset_id)
        .order_by(FuelLog.fillup_date.asc(), FuelLog.created_at.asc())
        .all()
    )
    total_cost = sum((log.total_cost for log in logs), Decimal("0"))
    total_gallons = sum((log.gallons or Decimal("0") for log in logs), Decimal("0"))
    mpg_values = list(calculate_mpg(logs).values())
    latest_mileage = max(
        (log.mileage_at_fillup for log in logs if log.mileage_at_fillup is not None),
        default=None,
    )
    return {
        "fillup_count": len(logs),
        "total_cost": total_cost.quantize(Decimal("0.01")),
        "total_gallons": total_gallons.quantize(Decimal("0.001")),
        "average_price": (
            (total_cost / total_gallons).quantize(Decimal("0.001"))
            if total_gallons > 0
            else Decimal("0")
        ),
        "average_mpg": (
            (sum(mpg_values, Decimal("0")) / Decimal(len(mpg_values))).quantize(Decimal("0.1"))
            if mpg_values
            else None
        ),
        "latest_mileage": latest_mileage,
    }


def _normalize_money_fields(data: dict) -> None:
    if data.get("fillup_date") is None:
        data["fillup_date"] = date.today()
    gallons = data.get("gallons")
    price = data.get("cost_per_gallon")
    total = data.get("total_cost")
    if gallons and total and not price:
        data["cost_per_gallon"] = (total / gallons).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )


def _validate(asset: Asset, data: dict) -> None:
    if asset.category != "vehicle":
        raise ValueError("Fuel logs are only available for vehicles")
    if asset.status == "retired":
        raise ValueError("Cannot add fuel logs to retired assets")
    if data.get("fillup_date") > date.today():
        raise ValueError("Fillup date cannot be in the future")
    if data.get("total_cost") is None:
        raise ValueError("Total cost is required")
    if data["total_cost"] <= 0:
        raise ValueError("Total cost must be positive")
    for field in ("gallons", "cost_per_gallon"):
        if data.get(field) is not None and data[field] <= 0:
            raise ValueError(f"{field.replace('_', ' ').title()} must be positive")
    ensure_nonnegative_int(
        data.get("mileage_at_fillup"), "Mileage at fillup", upper=MAX_MILEAGE
    )
    ensure_short_text(data.get("station"), "Station")
    ensure_long_text(data.get("notes"), "Notes")
    ensure_money_upper(data.get("gallons"), "Gallons", MAX_GALLONS)
    ensure_money_upper(
        data.get("cost_per_gallon"), "Cost per gallon", MAX_PRICE_PER_GALLON
    )


def _maybe_update_vehicle_mileage(db: Session, asset: Asset, mileage: int) -> None:
    if asset.vehicle_meta is None:
        asset.vehicle_meta = VehicleMeta()
    current = asset.vehicle_meta.current_mileage
    if current is None or mileage > current:
        asset.vehicle_meta.current_mileage = mileage
        db.add(asset.vehicle_meta)

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.recurring_cost import (
    RECURRING_COST_CATEGORIES,
    RECURRING_FREQUENCIES,
    RecurringCost,
)
from app.models.user import User
from app.services.validation import (
    ensure_date_in_range,
    ensure_long_text,
    ensure_positive_money,
    ensure_short_text,
)

RECURRING_COST_ALLOWED_FIELDS = {
    "name",
    "amount",
    "frequency",
    "start_date",
    "end_date",
    "cost_category",
    "notes",
}

# Number of occurrences per year for each frequency.
FREQUENCY_ANNUAL_MULTIPLIER: dict[str, Decimal] = {
    "one_time": Decimal("0"),
    "weekly": Decimal("52"),
    "monthly": Decimal("12"),
    "quarterly": Decimal("4"),
    "semi_annually": Decimal("2"),
    "annually": Decimal("1"),
}


def _filter_allowed(data: dict, allowed: set) -> dict:
    return {k: v for k, v in data.items() if k in allowed}


def annualize_amount(amount: Decimal | None, frequency: str) -> Decimal:
    """Return the annualized cost for an amount at the given frequency.

    One-time costs have no ongoing annual impact, so they contribute 0 here.
    """
    if amount is None:
        return Decimal("0")
    multiplier = FREQUENCY_ANNUAL_MULTIPLIER.get(frequency, Decimal("0"))
    return Decimal(str(amount)) * multiplier


def monthly_from_annual(annual: Decimal) -> Decimal:
    return (annual / Decimal("12")).quantize(Decimal("0.01"))


def list_recurring_costs(db: Session, asset_id: uuid.UUID) -> list[RecurringCost]:
    return (
        db.query(RecurringCost)
        .options(joinedload(RecurringCost.created_by))
        .filter(RecurringCost.asset_id == asset_id)
        .order_by(RecurringCost.start_date.desc())
        .all()
    )


def get_recurring_cost(db: Session, cost_id: uuid.UUID) -> RecurringCost | None:
    return (
        db.query(RecurringCost)
        .options(joinedload(RecurringCost.created_by))
        .filter(RecurringCost.id == cost_id)
        .first()
    )


def create_recurring_cost(
    db: Session,
    asset_id: uuid.UUID,
    data: dict,
    user: User,
) -> RecurringCost:
    filtered = _filter_allowed(data, RECURRING_COST_ALLOWED_FIELDS)
    _validate(filtered)
    cost = RecurringCost(asset_id=asset_id, created_by_id=user.id, **filtered)
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost


def update_recurring_cost(
    db: Session,
    cost: RecurringCost,
    data: dict,
) -> RecurringCost:
    filtered = _filter_allowed(data, RECURRING_COST_ALLOWED_FIELDS)
    _validate(filtered)
    for key, value in filtered.items():
        setattr(cost, key, value)
    db.commit()
    db.refresh(cost)
    return cost


def delete_recurring_cost(db: Session, cost: RecurringCost) -> None:
    db.delete(cost)
    db.commit()


def get_recurring_summary(db: Session, asset_id: uuid.UUID) -> dict:
    """Return counts and projected obligations for active recurring costs.

    Active = end_date is null or end_date >= today. One-time costs contribute
    to the count but have zero annualized impact.
    """
    today = date.today()
    rows = (
        db.query(RecurringCost.amount, RecurringCost.frequency)
        .filter(RecurringCost.asset_id == asset_id)
        .filter(or_(RecurringCost.end_date.is_(None), RecurringCost.end_date >= today))
        .all()
    )
    annual = Decimal("0")
    for amount, frequency in rows:
        annual += annualize_amount(amount, frequency)
    return {
        "count": len(rows),
        "annual_obligation": annual.quantize(Decimal("0.01")),
        "monthly_obligation": monthly_from_annual(annual),
    }


def _validate(data: dict) -> None:
    if "frequency" in data and data["frequency"] not in RECURRING_FREQUENCIES:
        raise ValueError(f"Invalid frequency: {data['frequency']!r}")
    if "cost_category" in data and data["cost_category"] not in RECURRING_COST_CATEGORIES:
        raise ValueError(f"Invalid cost category: {data['cost_category']!r}")
    ensure_short_text(data.get("name"), "Name")
    ensure_long_text(data.get("notes"), "Notes")
    if data.get("amount") is not None:
        ensure_positive_money(data["amount"], "Amount", allow_zero=False)
    if data.get("start_date") is not None:
        ensure_date_in_range(data["start_date"], "Start date")
    if data.get("end_date") is not None:
        ensure_date_in_range(data["end_date"], "End date")
    start = data.get("start_date")
    end = data.get("end_date")
    if start and end and end < start:
        raise ValueError("End date must be on or after start date")

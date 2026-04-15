from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

RECURRING_FREQUENCIES = [
    "one_time",
    "weekly",
    "monthly",
    "quarterly",
    "semi_annually",
    "annually",
]

RECURRING_COST_CATEGORIES = [
    "insurance",
    "registration",
    "fuel",
    "subscription",
    "tax",
    "fee",
    "other",
]


class RecurringCost(Base):
    __tablename__ = "recurring_costs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    start_date: Mapped[date] = mapped_column()
    end_date: Mapped[date | None] = mapped_column(default=None)
    cost_category: Mapped[str] = mapped_column(String(50), default="other")
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    asset: Mapped[Asset] = relationship(back_populates="recurring_costs")  # noqa: F821
    created_by: Mapped[User] = relationship()  # noqa: F821

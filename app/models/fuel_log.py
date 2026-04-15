from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FuelLog(Base):
    __tablename__ = "fuel_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    fillup_date: Mapped[date] = mapped_column()
    gallons: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), default=None)
    cost_per_gallon: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), default=None)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    mileage_at_fillup: Mapped[int | None] = mapped_column(default=None)
    full_tank: Mapped[bool] = mapped_column(default=True)
    station: Mapped[str | None] = mapped_column(String(200), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    asset: Mapped[Asset] = relationship(back_populates="fuel_logs")  # noqa: F821
    created_by: Mapped[User] = relationship()  # noqa: F821

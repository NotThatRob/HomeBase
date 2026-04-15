from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    subcategory: Mapped[str | None] = mapped_column(String(100), default=None)
    make: Mapped[str | None] = mapped_column(String(100), default=None)
    model_name: Mapped[str | None] = mapped_column(String(100), default=None)
    year: Mapped[int | None] = mapped_column(default=None)
    serial_number: Mapped[str | None] = mapped_column(String(200), default=None)
    purchase_date: Mapped[date | None] = mapped_column(default=None)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    purchase_vendor: Mapped[str | None] = mapped_column(String(200), default=None)
    warranty_expiration: Mapped[date | None] = mapped_column(default=None)
    warranty_notes: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str | None] = mapped_column(String(200), default=None)
    photo: Mapped[str | None] = mapped_column(String(500), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")
    retired_date: Mapped[date | None] = mapped_column(default=None)
    retired_reason: Mapped[str | None] = mapped_column(Text, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    visibility: Mapped[str] = mapped_column(String(20), default="shared")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    created_by: Mapped[User] = relationship()  # noqa: F821
    vehicle_meta: Mapped[VehicleMeta | None] = relationship(  # noqa: F821
        back_populates="asset", uselist=False, cascade="all, delete-orphan"
    )
    components: Mapped[list[Component]] = relationship(  # noqa: F821
        back_populates="asset", cascade="all, delete-orphan", order_by="Component.name"
    )
    service_records: Mapped[list[ServiceRecord]] = relationship(  # noqa: F821
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="ServiceRecord.service_date.desc()",
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="Document.uploaded_at.desc()",
    )
    maintenance_tasks: Mapped[list[MaintenanceTask]] = relationship(  # noqa: F821
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="MaintenanceTask.next_due.asc().nullslast()",
    )
    recurring_costs: Mapped[list[RecurringCost]] = relationship(  # noqa: F821
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="RecurringCost.start_date.desc()",
    )
    fuel_logs: Mapped[list[FuelLog]] = relationship(  # noqa: F821
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="FuelLog.fillup_date.desc()",
    )

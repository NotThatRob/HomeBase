from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.component import service_record_components

COST_CATEGORIES = ["maintenance", "repair", "inspection", "upgrade", "other"]


class ServiceRecord(Base):
    __tablename__ = "service_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    service_date: Mapped[date] = mapped_column()
    vendor: Mapped[str | None] = mapped_column(String(200), default=None)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    cost_category: Mapped[str] = mapped_column(String(50), default="maintenance")
    mileage_at_service: Mapped[int | None] = mapped_column(Integer, default=None)
    is_diy: Mapped[bool] = mapped_column(Boolean, default=False)
    next_service_notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    asset: Mapped[Asset] = relationship(back_populates="service_records")  # noqa: F821
    created_by: Mapped[User] = relationship()  # noqa: F821
    components: Mapped[list[Component]] = relationship(  # noqa: F821
        secondary=service_record_components, back_populates="service_records"
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        back_populates="service_record",
        order_by="Document.uploaded_at.desc()",
    )

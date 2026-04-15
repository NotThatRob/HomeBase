from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VehicleMeta(Base):
    __tablename__ = "vehicle_meta"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), unique=True)
    vin: Mapped[str | None] = mapped_column(String(17), default=None)
    license_plate: Mapped[str | None] = mapped_column(String(20), default=None)
    current_mileage: Mapped[int | None] = mapped_column(default=None)
    fuel_type: Mapped[str | None] = mapped_column(String(20), default=None)
    insurance_info: Mapped[str | None] = mapped_column(Text, default=None)

    asset: Mapped[Asset] = relationship(back_populates="vehicle_meta")  # noqa: F821

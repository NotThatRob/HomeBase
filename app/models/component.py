from __future__ import annotations

import uuid

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Join table for M2M between ServiceRecord and Component
service_record_components = Table(
    "service_record_components",
    Base.metadata,
    Column(
        "service_record_id",
        ForeignKey("service_records.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "component_id",
        ForeignKey("components.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Join table for M2M between Document and Component
document_components = Table(
    "document_components",
    Base.metadata,
    Column(
        "document_id",
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "component_id",
        ForeignKey("components.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Component(Base):
    __tablename__ = "components"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, default=None)

    asset: Mapped[Asset] = relationship(back_populates="components")  # noqa: F821
    service_records: Mapped[list[ServiceRecord]] = relationship(  # noqa: F821
        secondary=service_record_components, back_populates="components"
    )
    documents: Mapped[list[Document]] = relationship(  # noqa: F821
        secondary=document_components, back_populates="components"
    )
    maintenance_tasks: Mapped[list[MaintenanceTask]] = relationship(  # noqa: F821
        secondary="maintenance_task_components",
        back_populates="components",
    )

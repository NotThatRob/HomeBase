from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

maintenance_task_components = Table(
    "maintenance_task_components",
    Base.metadata,
    Column(
        "maintenance_task_id",
        ForeignKey("maintenance_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "component_id",
        ForeignKey("components.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

SCHEDULE_TYPES = ["one_time", "interval", "calendar", "usage"]
INTERVAL_UNITS = ["days", "weeks", "months", "years"]
TASK_PRIORITIES = ["low", "normal", "high", "critical"]
TASK_STATUSES = ["upcoming", "due", "overdue", "completed", "paused"]


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    schedule_type: Mapped[str] = mapped_column(String(20))
    interval_value: Mapped[int | None] = mapped_column(Integer, default=None)
    interval_unit: Mapped[str | None] = mapped_column(String(20), default=None)
    calendar_month: Mapped[int | None] = mapped_column(Integer, default=None)
    calendar_day: Mapped[int | None] = mapped_column(Integer, default=None)
    usage_trigger_label: Mapped[str | None] = mapped_column(String(50), default=None)
    usage_trigger_value: Mapped[int | None] = mapped_column(Integer, default=None)
    next_due: Mapped[date | None] = mapped_column(default=None)
    next_due_usage_value: Mapped[int | None] = mapped_column(Integer, default=None)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="upcoming")
    last_completed_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_records.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    asset: Mapped[Asset] = relationship(back_populates="maintenance_tasks")  # noqa: F821
    created_by: Mapped[User] = relationship()  # noqa: F821
    last_completed_record: Mapped[ServiceRecord | None] = relationship(  # noqa: F821
        foreign_keys=[last_completed_record_id]
    )
    components: Mapped[list[Component]] = relationship(  # noqa: F821
        secondary=maintenance_task_components,
        back_populates="maintenance_tasks",
    )

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.component import document_components

DOC_TYPES = [
    "manual",
    "receipt",
    "warranty",
    "invoice",
    "photo",
    "email",
    "report",
    "other",
]


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    service_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_records.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column(String(200))
    doc_type: Mapped[str] = mapped_column(String(20), default="other")
    file_path: Mapped[str] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())

    asset: Mapped[Asset] = relationship(back_populates="documents")  # noqa: F821
    service_record: Mapped[ServiceRecord | None] = relationship(  # noqa: F821
        back_populates="documents"
    )
    uploaded_by: Mapped[User] = relationship()  # noqa: F821
    components: Mapped[list[Component]] = relationship(  # noqa: F821
        secondary=document_components, back_populates="documents"
    )

import uuid
from datetime import datetime

import bcrypt
from sqlalchemy import JSON, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    session_version: Mapped[int] = mapped_column(default=0, server_default="0")
    wizard_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    email_digest_frequency: Mapped[str] = mapped_column(
        String(20), default="daily", server_default="daily"
    )
    email_digest_time: Mapped[str] = mapped_column(
        String(5), default="08:00", server_default="08:00"
    )
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(512), default=None)
    totp_pending_secret_encrypted: Mapped[str | None] = mapped_column(String(512), default=None)
    totp_pending_created_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    recovery_codes: Mapped[list[dict] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(default=None)

    def set_password(self, plain_password: str) -> None:
        self.password_hash = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode(
            "utf-8"
        )

    def verify_password(self, plain_password: str) -> bool:
        return bcrypt.checkpw(plain_password.encode("utf-8"), self.password_hash.encode("utf-8"))

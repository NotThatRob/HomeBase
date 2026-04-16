"""add totp mfa fields

Revision ID: e2f9b7c6a1d4
Revises: 9e2ac8f1b6d4
Create Date: 2026-04-16 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f9b7c6a1d4"
down_revision: str | Sequence[str] | None = "9e2ac8f1b6d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.String(512), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_pending_secret_encrypted", sa.String(512), nullable=True),
    )
    op.add_column("users", sa.Column("totp_pending_created_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("recovery_codes", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_pending_created_at")
    op.drop_column("users", "totp_pending_secret_encrypted")
    op.drop_column("users", "totp_secret_encrypted")

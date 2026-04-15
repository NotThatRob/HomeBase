"""add user active status

Revision ID: 9e2ac8f1b6d4
Revises: b8d5f1c9204a
Create Date: 2026-04-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e2ac8f1b6d4"
down_revision: str | Sequence[str] | None = "b8d5f1c9204a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "is_active")

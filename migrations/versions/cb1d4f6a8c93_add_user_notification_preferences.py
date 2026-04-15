"""add user notification preferences

Revision ID: cb1d4f6a8c93
Revises: bf6b4c7a9e21
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cb1d4f6a8c93"
down_revision: Union[str, Sequence[str], None] = "bf6b4c7a9e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "email_digest_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_digest_frequency",
            sa.String(length=20),
            server_default="daily",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_digest_time",
            sa.String(length=5),
            server_default="08:00",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "email_digest_time")
    op.drop_column("users", "email_digest_frequency")
    op.drop_column("users", "email_digest_enabled")

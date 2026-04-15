"""add user session_version

Revision ID: a3b99f4f7e2a
Revises: 2dbc52a0e9d8
Create Date: 2026-04-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3b99f4f7e2a"
down_revision: Union[str, Sequence[str], None] = "2dbc52a0e9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "session_version")

"""add fuel logs

Revision ID: b8d5f1c9204a
Revises: 79e63602b870
Create Date: 2026-04-14 09:25:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b8d5f1c9204a"
down_revision: Union[str, Sequence[str], None] = "79e63602b870"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "fuel_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("fillup_date", sa.Date(), nullable=False),
        sa.Column("gallons", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("cost_per_gallon", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("mileage_at_fillup", sa.Integer(), nullable=True),
        sa.Column("full_tank", sa.Boolean(), nullable=False),
        sa.Column("station", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("fuel_logs")

"""add maintenance tasks

Revision ID: bf6b4c7a9e21
Revises: a3b99f4f7e2a
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bf6b4c7a9e21"
down_revision: Union[str, Sequence[str], None] = "a3b99f4f7e2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "maintenance_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schedule_type", sa.String(length=20), nullable=False),
        sa.Column("interval_value", sa.Integer(), nullable=True),
        sa.Column("interval_unit", sa.String(length=20), nullable=True),
        sa.Column("calendar_month", sa.Integer(), nullable=True),
        sa.Column("calendar_day", sa.Integer(), nullable=True),
        sa.Column("usage_trigger_label", sa.String(length=50), nullable=True),
        sa.Column("usage_trigger_value", sa.Integer(), nullable=True),
        sa.Column("next_due", sa.Date(), nullable=True),
        sa.Column("next_due_usage_value", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_completed_record_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["last_completed_record_id"], ["service_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "maintenance_task_components",
        sa.Column("maintenance_task_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["component_id"], ["components.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["maintenance_task_id"], ["maintenance_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("maintenance_task_id", "component_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("maintenance_task_components")
    op.drop_table("maintenance_tasks")

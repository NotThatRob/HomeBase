"""add user wizard_completed

Revision ID: 2dbc52a0e9d8
Revises: 4ed2fc569c7f
Create Date: 2026-04-10 20:31:17.196667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2dbc52a0e9d8'
down_revision: Union[str, Sequence[str], None] = '4ed2fc569c7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column(
            'wizard_completed',
            sa.Boolean(),
            server_default='false',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'wizard_completed')

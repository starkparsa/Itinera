"""add trips events columns

Revision ID: 6b2dca1a5047
Revises: e75cacca6864
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b2dca1a5047'
down_revision: Union[str, Sequence[str], None] = 'e75cacca6864'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Both nullable -- no server_default needed against a trips table that
    # already has rows, same as ccdfae4d6065's photo columns.
    op.add_column('trips', sa.Column('events_json', sa.Text(), nullable=True))
    op.add_column('trips', sa.Column('events_fetched_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('trips', 'events_fetched_at')
    op.drop_column('trips', 'events_json')

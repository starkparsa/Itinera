"""add trips photo columns

Revision ID: ccdfae4d6065
Revises: 4e14c7bab841
Create Date: 2026-09-04 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ccdfae4d6065'
down_revision: Union[str, Sequence[str], None] = '4e14c7bab841'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # All three columns are nullable -- no server_default needed even
    # against a trips table that already has rows (unlike the
    # daily_request_count column in 4e14c7bab841, which was NOT NULL and
    # needed one).
    op.add_column('trips', sa.Column('photo_url', sa.String(length=500), nullable=True))
    op.add_column('trips', sa.Column('photo_credit', sa.String(length=255), nullable=True))
    op.add_column('trips', sa.Column('photo_fetched_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('trips', 'photo_fetched_at')
    op.drop_column('trips', 'photo_credit')
    op.drop_column('trips', 'photo_url')

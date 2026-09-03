"""add saved_places table

Revision ID: 26570b0251ed
Revises: ccdfae4d6065
Create Date: 2026-09-04 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26570b0251ed'
down_revision: Union[str, Sequence[str], None] = 'ccdfae4d6065'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'saved_places',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        # Sized for Google Places' own priceLevel enum values, e.g.
        # "PRICE_LEVEL_VERY_EXPENSIVE" (26 chars).
        sa.Column('price_level', sa.String(length=40), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    # Same indexing convention as every other FK in this app (see
    # 98900a8d691c_add_indexes_on_foreign_key_columns.py) -- saved_places
    # is always queried by trip_id (routers/trips.py's dedupe check and
    # the Trip.saved_places relationship load).
    op.create_index('ix_saved_places_id', 'saved_places', ['id'])
    op.create_index('ix_saved_places_trip_id', 'saved_places', ['trip_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_saved_places_trip_id', table_name='saved_places')
    op.drop_index('ix_saved_places_id', table_name='saved_places')
    op.drop_table('saved_places')

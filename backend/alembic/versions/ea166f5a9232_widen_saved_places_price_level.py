"""widen saved_places price_level

Revision ID: ea166f5a9232
Revises: 26570b0251ed
Create Date: 2026-09-04 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea166f5a9232'
down_revision: Union[str, Sequence[str], None] = '26570b0251ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    26570b0251ed's own migration file already specified VARCHAR(40), but
    the live dev database ended up with VARCHAR(20) instead -- main.py's
    Base.metadata.create_all() (a documented no-op-on-existing-tables
    safety net, see its comment) silently created the `saved_places` table
    on a dev-server auto-reload BEFORE the price_level width was widened
    in models.py, and create_all never alters an existing table's column
    types. This migration catches that table up to match the model.
    """
    op.alter_column('saved_places', 'price_level', type_=sa.String(length=40))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('saved_places', 'price_level', type_=sa.String(length=20))

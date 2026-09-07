"""add user_profiles account details columns

Revision ID: e75cacca6864
Revises: 05db88c6b402
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e75cacca6864'
down_revision: Union[str, Sequence[str], None] = '05db88c6b402'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_profiles', sa.Column('mobile_number', sa.String(length=30), nullable=True))
    op.add_column('user_profiles', sa.Column('date_of_birth', sa.Date(), nullable=True))
    op.add_column('user_profiles', sa.Column('country_region', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_profiles', 'country_region')
    op.drop_column('user_profiles', 'date_of_birth')
    op.drop_column('user_profiles', 'mobile_number')

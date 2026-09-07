"""add user_profiles table

Revision ID: 05db88c6b402
Revises: ea166f5a9232
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05db88c6b402'
down_revision: Union[str, Sequence[str], None] = 'ea166f5a9232'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('user_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('travel_frequency', sa.String(length=30), nullable=True),
    sa.Column('pace', sa.String(length=20), nullable=True),
    sa.Column('budget_tier', sa.String(length=20), nullable=True),
    sa.Column('interests', sa.Text(), nullable=True),
    sa.Column('travel_companions', sa.String(length=30), nullable=True),
    sa.Column('typical_trip_length_days', sa.Integer(), nullable=True),
    sa.Column('dietary_needs', sa.Text(), nullable=True),
    sa.Column('accessibility_needs', sa.Text(), nullable=True),
    sa.Column('bucket_list_countries', sa.Text(), nullable=True),
    sa.Column('additional_preferences', sa.Text(), nullable=True),
    sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True),
    sa.Column('onboarding_skipped_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_user_profiles_id'), 'user_profiles', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_user_profiles_id'), table_name='user_profiles')
    op.drop_table('user_profiles')

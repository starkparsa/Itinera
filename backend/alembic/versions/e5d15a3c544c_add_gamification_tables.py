"""add gamification tables

Revision ID: e5d15a3c544c
Revises: 6b2dca1a5047
Create Date: 2026-09-07 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5d15a3c544c'
down_revision: Union[str, Sequence[str], None] = '6b2dca1a5047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # is_edit: NOT NULL against a trips table that already has rows, so
    # this needs a server_default (unlike the purely nullable columns
    # added elsewhere) -- every pre-existing row reads as "not an edit",
    # the honest default since there's no way to reconstruct which
    # historical rows actually came from an edit_trip turn.
    op.add_column('trips', sa.Column('is_edit', sa.Boolean(), nullable=False, server_default='0'))

    op.create_table(
        'user_stats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('xp_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_user_stats_id', 'user_stats', ['id'])
    op.create_index('ix_user_stats_user_id', 'user_stats', ['user_id'])

    # The unique constraint is declared inline in create_table (not a
    # separate op.create_unique_constraint after the fact) specifically so
    # this works against SQLite too -- SQLite has no ALTER TABLE support
    # for adding a constraint to an existing table (alembic raises
    # NotImplementedError for that), but including it in the original
    # CREATE TABLE statement works on both SQLite and Postgres.
    op.create_table(
        'user_achievements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('earned_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'code', name='uq_user_achievements_user_code'),
    )
    op.create_index('ix_user_achievements_id', 'user_achievements', ['id'])
    op.create_index('ix_user_achievements_user_id', 'user_achievements', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_achievements_user_id', table_name='user_achievements')
    op.drop_index('ix_user_achievements_id', table_name='user_achievements')
    op.drop_table('user_achievements')

    op.drop_index('ix_user_stats_user_id', table_name='user_stats')
    op.drop_index('ix_user_stats_id', table_name='user_stats')
    op.drop_table('user_stats')

    op.drop_column('trips', 'is_edit')

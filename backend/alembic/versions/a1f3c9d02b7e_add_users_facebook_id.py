"""add users facebook_id

Revision ID: a1f3c9d02b7e
Revises: 0668d9be3ecf
Create Date: 2026-09-07 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d02b7e'
down_revision: Union[str, Sequence[str], None] = '0668d9be3ecf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, unique, indexed -- same nullable-per-auth-method shape as
    # google_sub/password_hash above; no server_default needed against a
    # users table that already has rows.
    op.add_column('users', sa.Column('facebook_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_users_facebook_id'), 'users', ['facebook_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_facebook_id'), table_name='users')
    op.drop_column('users', 'facebook_id')

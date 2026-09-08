"""add users password_hash

Revision ID: 0668d9be3ecf
Revises: e5d15a3c544c
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0668d9be3ecf'
down_revision: Union[str, Sequence[str], None] = 'e5d15a3c544c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable -- no server_default needed against a users table that
    # already has rows, same as every other nullable-per-auth-method
    # column added to this table (google_sub).
    op.add_column('users', sa.Column('password_hash', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'password_hash')

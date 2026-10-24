"""free the logins of users who are in no home

Revision ID: c3f1a9d2e4b7
Revises: 6d1d145e288c
Create Date: 2026-10-23 17:40:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a9d2e4b7"
down_revision: Union[str, Sequence[str], None] = "6d1d145e288c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """People removed from every home before this change kept their login,
    so it could not be used again. Close those accounts and free the login."""
    op.execute(
        "UPDATE users SET email = 'deleted:' || id, is_active = 0, "
        "hashed_password = '!' "
        "WHERE id NOT IN (SELECT user_id FROM home_memberships) "
        "AND email NOT LIKE 'deleted:%'"
    )


def downgrade() -> None:
    """The old logins are not kept, so this cannot be undone."""

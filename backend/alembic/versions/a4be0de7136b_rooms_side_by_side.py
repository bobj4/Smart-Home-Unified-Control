"""rooms side by side

Revision ID: a4be0de7136b
Revises: 81a51a207dec
Create Date: 2026-11-06 10:10:21.575423

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4be0de7136b"
down_revision: Union[str, Sequence[str], None] = "81a51a207dec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rooms side by side on larger screens: columns and each room's width."""
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.add_column(sa.Column("grid", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.drop_column("grid")

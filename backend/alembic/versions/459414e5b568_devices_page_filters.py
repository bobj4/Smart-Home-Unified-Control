"""devices page filters

Revision ID: 459414e5b568
Revises: 6b81bac4dd34
Create Date: 2026-11-05 22:02:01.573240

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "459414e5b568"
down_revision: Union[str, Sequence[str], None] = "6b81bac4dd34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The Devices page filters each person last used (search, type, on only)."""
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.add_column(sa.Column("filters", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.drop_column("filters")

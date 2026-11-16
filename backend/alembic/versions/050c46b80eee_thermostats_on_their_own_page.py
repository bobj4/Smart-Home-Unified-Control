"""thermostats on their own page

Revision ID: 050c46b80eee
Revises: 459414e5b568
Create Date: 2026-11-05 22:03:57.046793

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "050c46b80eee"
down_revision: Union[str, Sequence[str], None] = "459414e5b568"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A person can keep the thermostats on their own page only."""
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "thermostats_apart",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.drop_column("thermostats_apart")

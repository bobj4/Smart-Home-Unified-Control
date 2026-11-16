"""doors on their own page

Revision ID: c71d0e5a9b23
Revises: a852a84aff09
Create Date: 2026-11-06 17:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c71d0e5a9b23"
down_revision: Union[str, Sequence[str], None] = "a852a84aff09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A person can keep the remote doors on their own page only."""
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "doors_apart",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.drop_column("doors_apart")

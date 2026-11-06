"""room layout per screen and collapsed rooms

Revision ID: 6b81bac4dd34
Revises: 6f4aaa5a1a45
Create Date: 2026-11-05 21:49:00.598052

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b81bac4dd34"
down_revision: Union[str, Sequence[str], None] = "6f4aaa5a1a45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A layout per screen type (phone or wide) and the rooms folded shut.
    Existing layouts become the wide-screen ones."""
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "screen", sa.String(length=10), server_default="wide", nullable=False
            )
        )
        batch_op.add_column(sa.Column("collapsed", sa.Text(), nullable=True))
        batch_op.drop_constraint("uq_room_layout_user_home", type_="unique")
        batch_op.create_unique_constraint(
            "uq_room_layout_user_home_screen", ["user_id", "home_id", "screen"]
        )


def downgrade() -> None:
    op.execute("DELETE FROM room_layouts WHERE screen != 'wide'")
    with op.batch_alter_table("room_layouts") as batch_op:
        batch_op.drop_constraint("uq_room_layout_user_home_screen", type_="unique")
        batch_op.create_unique_constraint(
            "uq_room_layout_user_home", ["user_id", "home_id"]
        )
        batch_op.drop_column("collapsed")
        batch_op.drop_column("screen")

"""custom background image

Revision ID: 6f4aaa5a1a45
Revises: bfdc4baf363d
Create Date: 2026-11-05 21:36:51.199862

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f4aaa5a1a45"
down_revision: Union[str, Sequence[str], None] = "bfdc4baf363d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A picture behind the dashboard, chosen per person, with an on/off switch."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("background_image", sa.LargeBinary(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("background_type", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "background_on", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("background_on")
        batch_op.drop_column("background_type")
        batch_op.drop_column("background_image")

"""custom theme colour

Revision ID: bfdc4baf363d
Revises: 102cab62ecc9
Create Date: 2026-11-05 21:31:30.934533

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bfdc4baf363d"
down_revision: Union[str, Sequence[str], None] = "102cab62ecc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A custom theme: the chosen colour and a dark or light base."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("theme_custom", sa.String(length=16), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("theme_custom")

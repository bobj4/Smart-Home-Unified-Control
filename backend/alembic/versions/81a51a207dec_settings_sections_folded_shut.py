"""settings sections folded shut

Revision ID: 81a51a207dec
Revises: 96d9a6155492
Create Date: 2026-11-05 22:44:43.916042

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "81a51a207dec"
down_revision: Union[str, Sequence[str], None] = "96d9a6155492"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The Settings sections each person folded shut (a JSON list)."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("settings_collapsed", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("settings_collapsed")

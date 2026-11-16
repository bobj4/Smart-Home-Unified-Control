"""users may edit their own name and email

Revision ID: 96d9a6155492
Revises: b983a66bc188
Create Date: 2026-11-05 22:09:38.262015

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "96d9a6155492"
down_revision: Union[str, Sequence[str], None] = "b983a66bc188"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Admin setting: people may change their own name and email (off)."""
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "users_edit_own_info",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.drop_column("users_edit_own_info")

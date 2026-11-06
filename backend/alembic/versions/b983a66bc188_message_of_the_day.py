"""message of the day

Revision ID: b983a66bc188
Revises: 050c46b80eee
Create Date: 2026-11-05 22:06:45.438924

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b983a66bc188"
down_revision: Union[str, Sequence[str], None] = "050c46b80eee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """An optional message shown to everyone after login, until dismissed."""
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.add_column(sa.Column("motd_text", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("motd_version", sa.Integer(), server_default="0", nullable=False)
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "motd_dismissed", sa.Integer(), server_default="0", nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("motd_dismissed")
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.drop_column("motd_version")
        batch_op.drop_column("motd_text")

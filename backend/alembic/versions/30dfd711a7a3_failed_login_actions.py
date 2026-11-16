"""failed login actions

Revision ID: 30dfd711a7a3
Revises: ed8baf28016b
Create Date: 2026-10-30 11:17:11.122206

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "30dfd711a7a3"
down_revision: Union[str, Sequence[str], None] = "ed8baf28016b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: failed-login rule, and each account's count and lock."""
    with op.batch_alter_table("system_settings") as batch:
        batch.add_column(
            sa.Column(
                "login_failure_action",
                sa.String(10),
                nullable=False,
                server_default="none",
            )
        )
        batch.add_column(
            sa.Column(
                "login_failure_limit", sa.Integer(), nullable=True, server_default="10"
            )
        )
        batch.add_column(
            sa.Column(
                "login_lockout_minutes",
                sa.Integer(),
                nullable=True,
                server_default="15",
            )
        )
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_logins")
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("login_lockout_minutes")
        batch.drop_column("login_failure_limit")
        batch.drop_column("login_failure_action")

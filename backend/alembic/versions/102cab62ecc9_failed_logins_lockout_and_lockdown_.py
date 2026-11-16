"""failed logins: lockout and lockdown counts

Revision ID: 102cab62ecc9
Revises: 30dfd711a7a3
Create Date: 2026-11-05 21:02:09.597614

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "102cab62ecc9"
down_revision: Union[str, Sequence[str], None] = "30dfd711a7a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One count per rule instead of one action: lockout after N failures,
    lockdown after M. The old choice carries over."""
    with op.batch_alter_table("system_settings") as batch:
        batch.add_column(sa.Column("login_lockout_after", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("login_lockdown_after", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE system_settings SET login_lockout_after = login_failure_limit "
        "WHERE login_failure_action = 'lockout'"
    )
    op.execute(
        "UPDATE system_settings SET login_lockdown_after = login_failure_limit "
        "WHERE login_failure_action = 'lockdown'"
    )
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("login_failure_action")
        batch.drop_column("login_failure_limit")


def downgrade() -> None:
    """Back to one action (lockdown wins when both were set)."""
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
    op.execute(
        "UPDATE system_settings SET login_failure_action = 'lockout', "
        "login_failure_limit = login_lockout_after WHERE login_lockout_after IS NOT NULL"
    )
    op.execute(
        "UPDATE system_settings SET login_failure_action = 'lockdown', "
        "login_failure_limit = login_lockdown_after WHERE login_lockdown_after IS NOT NULL"
    )
    with op.batch_alter_table("system_settings") as batch:
        batch.drop_column("login_lockdown_after")
        batch.drop_column("login_lockout_after")

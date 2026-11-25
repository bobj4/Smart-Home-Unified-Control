"""homes: thermostats and doors only on their own pages, for everyone (was each person's)

Revision ID: f8b0d2e4a6c7
Revises: e7a9c1d3f5b6
Create Date: 2026-11-24 21:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8b0d2e4a6c7"
down_revision: str | None = "e7a9c1d3f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("homes") as batch:
        for name in ("thermostats_apart", "doors_apart"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), server_default=sa.false(), nullable=False)
            )
    # What an admin of the home chose for themselves becomes the home's.
    for name in ("thermostats_apart", "doors_apart"):
        op.execute(
            f"UPDATE homes SET {name} = TRUE WHERE id IN ("  # noqa: S608
            "SELECT l.home_id FROM room_layouts l JOIN home_memberships m "
            "ON m.home_id = l.home_id AND m.user_id = l.user_id "
            f"WHERE l.{name} = TRUE AND m.role = 'admin')"
        )
    with op.batch_alter_table("room_layouts") as batch:
        batch.drop_column("thermostats_apart")
        batch.drop_column("doors_apart")


def downgrade() -> None:
    with op.batch_alter_table("room_layouts") as batch:
        for name in ("thermostats_apart", "doors_apart"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), server_default=sa.false(), nullable=False)
            )
    with op.batch_alter_table("homes") as batch:
        batch.drop_column("doors_apart")
        batch.drop_column("thermostats_apart")

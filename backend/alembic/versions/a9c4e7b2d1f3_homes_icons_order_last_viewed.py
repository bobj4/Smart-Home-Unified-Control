"""homes: icon, each person's order of their homes, last viewed home

Revision ID: a9c4e7b2d1f3
Revises: f7a3c9d1e2b4
Create Date: 2026-11-12 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c4e7b2d1f3"
down_revision: Union[str, Sequence[str], None] = "f7a3c9d1e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("homes") as batch:
        batch.add_column(sa.Column("icon", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("icon_image", sa.Text(), nullable=True))
    with op.batch_alter_table("home_memberships") as batch:
        batch.add_column(
            sa.Column("position", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("last_home_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_home_id")
    with op.batch_alter_table("home_memberships") as batch:
        batch.drop_column("position")
    with op.batch_alter_table("homes") as batch:
        batch.drop_column("icon_image")
        batch.drop_column("icon")

"""scenes: Reset puts back what a scene changed

Revision ID: e7a9c1d3f5b6
Revises: d6f8a0c2e4b5
Create Date: 2026-11-24 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a9c1d3f5b6"
down_revision: str | None = "d6f8a0c2e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scenes") as batch:
        batch.add_column(sa.Column("before", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ran_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scenes") as batch:
        batch.drop_column("ran_at")
        batch.drop_column("before")

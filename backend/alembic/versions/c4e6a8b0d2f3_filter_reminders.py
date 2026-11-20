"""thermostats: air-filter reminders

Revision ID: c4e6a8b0d2f3
Revises: b2d4f6a8c0e1
Create Date: 2026-11-19 22:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e6a8b0d2f3"
down_revision: Union[str, Sequence[str], None] = "b2d4f6a8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "filter_reminders",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("every", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("runtime_at_change", sa.Float(), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )


def downgrade() -> None:
    op.drop_table("filter_reminders")

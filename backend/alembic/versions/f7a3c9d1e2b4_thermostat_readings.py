"""thermostat readings for the History window

Revision ID: f7a3c9d1e2b4
Revises: e5f9b2d3c8a1
Create Date: 2026-11-06 20:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a3c9d1e2b4"
down_revision: Union[str, Sequence[str], None] = "e5f9b2d3c8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "thermostat_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("heat_setpoint", sa.Float(), nullable=True),
        sa.Column("cool_setpoint", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=True),
        sa.Column("mode", sa.String(length=12), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_thermostat_readings_device_id", "thermostat_readings", ["device_id"]
    )
    op.create_index("ix_thermostat_readings_at", "thermostat_readings", ["at"])


def downgrade() -> None:
    op.drop_index("ix_thermostat_readings_at", table_name="thermostat_readings")
    op.drop_index("ix_thermostat_readings_device_id", table_name="thermostat_readings")
    op.drop_table("thermostat_readings")

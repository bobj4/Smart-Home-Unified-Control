"""alerts per device (the bells in Settings > Devices); location from address

Revision ID: a7c9e1b3d5f6
Revises: f1a3b5c7d9e2
Create Date: 2026-11-15 02:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9e1b3d5f6"
down_revision: Union[str, Sequence[str], None] = "f1a3b5c7d9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

HOME_WIDE = (
    "garage_open_minutes",
    "auto_close_minutes",
    "obstruction",
    "offline_minutes",
    "offline_types",
    "water_heater",
)


def upgrade() -> None:
    op.create_table(
        "device_alerts",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
    )
    # What each device watches for is now set per device.
    with op.batch_alter_table("alert_settings") as batch:
        for column in HOME_WIDE:
            batch.drop_column(column)
    with op.batch_alter_table("schedule_settings") as batch:
        batch.add_column(
            sa.Column(
                "location_source",
                sa.String(length=10),
                server_default="manual",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("schedule_settings") as batch:
        batch.drop_column("location_source")
    with op.batch_alter_table("alert_settings") as batch:
        batch.add_column(
            sa.Column(
                "garage_open_minutes", sa.Integer(), server_default="15", nullable=False
            )
        )
        batch.add_column(
            sa.Column(
                "auto_close_minutes", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch.add_column(
            sa.Column(
                "obstruction", sa.Boolean(), server_default=sa.true(), nullable=False
            )
        )
        batch.add_column(
            sa.Column(
                "offline_minutes", sa.Integer(), server_default="15", nullable=False
            )
        )
        batch.add_column(
            sa.Column(
                "offline_types",
                sa.String(length=200),
                server_default="thermostat,water_heater,garage_door",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "water_heater", sa.Boolean(), server_default=sa.true(), nullable=False
            )
        )
    op.drop_table("device_alerts")

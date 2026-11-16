"""guests: thermostat settings and installer settings

Revision ID: e5f9b2d3c8a1
Revises: d4e8a1c2b7f6
Create Date: 2026-11-06 20:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f9b2d3c8a1"
down_revision: Union[str, Sequence[str], None] = "d4e8a1c2b7f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A guest may open their thermostats' Settings, and change the
    installer settings there."""
    with op.batch_alter_table("guest_access") as batch_op:
        for column in ("thermostat_settings", "thermostat_installer"):
            batch_op.add_column(
                sa.Column(
                    column, sa.Boolean(), server_default=sa.false(), nullable=False
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("guest_access") as batch_op:
        batch_op.drop_column("thermostat_installer")
        batch_op.drop_column("thermostat_settings")

"""who may change thermostat installer settings

Revision ID: d4e8a1c2b7f6
Revises: c71d0e5a9b23
Create Date: 2026-11-06 20:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e8a1c2b7f6"
down_revision: Union[str, Sequence[str], None] = "c71d0e5a9b23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The lowest role that may change a thermostat's installer settings."""
    with op.batch_alter_table("homes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "thermostat_installer_role",
                sa.String(length=10),
                server_default="admin",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("homes") as batch_op:
        batch_op.drop_column("thermostat_installer_role")

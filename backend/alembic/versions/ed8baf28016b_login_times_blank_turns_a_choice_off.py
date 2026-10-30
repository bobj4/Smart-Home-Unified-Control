"""login times: blank turns a choice off

Revision ID: ed8baf28016b
Revises: 95dc1c78ab6c
Create Date: 2026-10-30 11:02:27.472366

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ed8baf28016b"
down_revision: Union[str, Sequence[str], None] = "95dc1c78ab6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = ("keep_logged_in_days", "remember_me_days", "remember_device_days")


def upgrade() -> None:
    """Upgrade schema: a blank login time (NULL) turns that choice off."""
    with op.batch_alter_table("system_settings") as batch:
        for name in COLUMNS:
            batch.alter_column(name, existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema: turned-off choices get their defaults back."""
    defaults = {
        "keep_logged_in_days": 30,
        "remember_me_days": 365,
        "remember_device_days": 0,
    }
    for name, value in defaults.items():
        op.execute(
            sa.text(
                f"UPDATE system_settings SET {name} = :v WHERE {name} IS NULL"
            ).bindparams(v=value)
        )
    with op.batch_alter_table("system_settings") as batch:
        for name in COLUMNS:
            batch.alter_column(name, existing_type=sa.Integer(), nullable=False)

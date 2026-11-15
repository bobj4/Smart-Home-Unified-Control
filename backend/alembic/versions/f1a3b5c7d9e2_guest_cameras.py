"""guests: only some cameras

Revision ID: f1a3b5c7d9e2
Revises: e9f2a4b6c8d0
Create Date: 2026-11-15 01:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a3b5c7d9e2"
down_revision: Union[str, Sequence[str], None] = "e9f2a4b6c8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("guest_access") as batch:
        batch.add_column(
            sa.Column("camera_names", sa.Text(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("guest_access") as batch:
        batch.drop_column("camera_names")

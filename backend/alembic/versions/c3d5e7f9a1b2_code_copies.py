"""enrollment and reset codes: an encrypted copy to show while active

Revision ID: c3d5e7f9a1b2
Revises: b7e2d4f6a8c1
Create Date: 2026-11-13 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d5e7f9a1b2"
down_revision: Union[str, Sequence[str], None] = "b7e2d4f6a8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("enrollments", "password_resets"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("code_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in ("enrollments", "password_resets"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("code_secret")

"""add_default_target_to_safety_limits

Revision ID: 6ba1863e60b4
Revises: 39880655b171
Create Date: 2026-10-20 22:20:31.614464

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6ba1863e60b4"
down_revision: Union[str, Sequence[str], None] = "39880655b171"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "device_safety_limits", sa.Column("default_target", sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("device_safety_limits", "default_target")

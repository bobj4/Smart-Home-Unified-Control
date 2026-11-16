"""homes at other sites: the link to a site's own server

Revision ID: b7e2d4f6a8c1
Revises: a9c4e7b2d1f3
Create Date: 2026-11-12 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2d4f6a8c1"
down_revision: Union[str, Sequence[str], None] = "a9c4e7b2d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("homes") as batch:
        batch.add_column(sa.Column("site_home_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column("site_token_hash", sa.String(length=64), nullable=True)
        )
        batch.add_column(sa.Column("site_name", sa.String(length=100), nullable=True))
        batch.add_column(
            sa.Column("site_pairing_hash", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("site_pairing_until", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("homes") as batch:
        for column in (
            "site_pairing_until",
            "site_pairing_hash",
            "site_name",
            "site_token_hash",
            "site_home_id",
        ):
            batch.drop_column(column)

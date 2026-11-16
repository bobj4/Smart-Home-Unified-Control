"""certificate auto import

Revision ID: a852a84aff09
Revises: a4be0de7136b
Create Date: 2026-11-06 11:34:28.192810

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a852a84aff09"
down_revision: Union[str, Sequence[str], None] = "a4be0de7136b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Take the HTTPS certificate from this server's web server, automatically."""
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cert_auto_import",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("cert_import_source", sa.String(length=300), nullable=True)
        )
        batch_op.add_column(
            sa.Column("cert_imported_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("system_settings") as batch_op:
        batch_op.drop_column("cert_imported_at")
        batch_op.drop_column("cert_import_source")
        batch_op.drop_column("cert_auto_import")

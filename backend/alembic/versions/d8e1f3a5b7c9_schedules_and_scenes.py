"""schedules and scenes: scenes, schedules run by the server, their settings

Revision ID: d8e1f3a5b7c9
Revises: c3d5e7f9a1b2
Create Date: 2026-11-14 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e1f3a5b7c9"
down_revision: Union[str, Sequence[str], None] = "c3d5e7f9a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scenes_home_id"), "scenes", ["home_id"], unique=False)
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("days", sa.Text(), nullable=False),
        sa.Column("scene_id", sa.String(length=36), nullable=True),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_result", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_id"], ["scenes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_schedules_home_id"), "schedules", ["home_id"], unique=False
    )
    op.create_index(
        op.f("ix_schedules_next_run_at"), "schedules", ["next_run_at"], unique=False
    )
    op.create_table(
        "schedule_settings",
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("time_zone", sa.String(length=64), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("editors", sa.String(length=10), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("home_id"),
    )
    with op.batch_alter_table("guest_access") as batch:
        batch.add_column(
            sa.Column("scenes", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("guest_access") as batch:
        batch.drop_column("scenes")
    op.drop_table("schedule_settings")
    op.drop_index(op.f("ix_schedules_next_run_at"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_home_id"), table_name="schedules")
    op.drop_table("schedules")
    op.drop_index(op.f("ix_scenes_home_id"), table_name="scenes")
    op.drop_table("scenes")

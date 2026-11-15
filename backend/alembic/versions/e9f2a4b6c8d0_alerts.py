"""alerts: home settings, people's choices, push subscriptions, keys, the bell

Revision ID: e9f2a4b6c8d0
Revises: d8e1f3a5b7c9
Create Date: 2026-11-14 23:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f2a4b6c8d0"
down_revision: Union[str, Sequence[str], None] = "d8e1f3a5b7c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_settings",
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("garage_open_minutes", sa.Integer(), nullable=False),
        sa.Column("auto_close_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "obstruction", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column("offline_minutes", sa.Integer(), nullable=False),
        sa.Column("offline_types", sa.String(length=200), nullable=False),
        sa.Column(
            "water_heater", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
        sa.Column("frigate_labels", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("home_id"),
    )
    op.create_table(
        "alert_prefs",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("push", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("kinds", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "home_id"),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint", sa.String(length=1000), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
    )
    op.create_index(
        op.f("ix_push_subscriptions_user_id"),
        "push_subscriptions",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "alert_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_alert_items_home_id"), "alert_items", ["home_id"], unique=False
    )
    op.create_index(
        op.f("ix_alert_items_created_at"), "alert_items", ["created_at"], unique=False
    )
    op.create_table(
        "alert_seen",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("home_id", sa.String(length=36), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["home_id"], ["homes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "home_id"),
    )
    op.create_table(
        "server_keys",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("server_keys")
    op.drop_table("alert_seen")
    op.drop_index(op.f("ix_alert_items_created_at"), table_name="alert_items")
    op.drop_index(op.f("ix_alert_items_home_id"), table_name="alert_items")
    op.drop_table("alert_items")
    op.drop_index(
        op.f("ix_push_subscriptions_user_id"), table_name="push_subscriptions"
    )
    op.drop_table("push_subscriptions")
    op.drop_table("alert_prefs")
    op.drop_table("alert_settings")

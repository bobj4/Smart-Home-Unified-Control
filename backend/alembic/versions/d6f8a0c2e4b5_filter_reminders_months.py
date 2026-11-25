"""thermostats: air-filter reminders as the Cync thermostat keeps them (run hours or months)

Revision ID: d6f8a0c2e4b5
Revises: c4e6a8b0d2f3
Create Date: 2026-11-20 06:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d6f8a0c2e4b5"
down_revision: str | None = "c4e6a8b0d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Days are not a Cync choice: the nearest whole months (1 to 12).
    op.execute(
        "UPDATE filter_reminders SET mode = 'months', every = CASE "
        "WHEN every < 45 THEN 1 WHEN every >= 345 THEN 12 "
        "ELSE (every + 15) / 30 END WHERE mode = 'days'"
    )
    # Run hours: the thermostat's 100 to 1500, in hundreds.
    op.execute(
        "UPDATE filter_reminders SET every = CASE "
        "WHEN every < 150 THEN 100 WHEN every >= 1450 THEN 1500 "
        "ELSE ((every + 50) / 100) * 100 END WHERE mode = 'hours'"
    )


def downgrade() -> None:
    pass  # the values are still valid reminders

"""Integrations (device brands) a home can turn on or off.

A turned-off integration accepts no commands and no new devices.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.models import HomeIntegration


@dataclass(frozen=True)
class Integration:
    id: str
    name: str
    description: str
    default_enabled: bool
    available: bool  # its code exists in this version


INTEGRATIONS: tuple[Integration, ...] = (
    Integration(
        "simulated",
        "Demo devices",
        "Simulated devices for trying the app without hardware.",
        True,
        True,
    ),
    Integration(
        "cync",
        "GE Cync",
        "Cync lights, plugs and the thermostat.",
        False,
        True,
    ),
    Integration(
        "samsung_tv", "Samsung TV", "Samsung smart TVs on your network.", False, True
    ),
    Integration(
        "rheem_econet",
        "Rheem EcoNet",
        "Rheem water heaters through EcoNet.",
        False,
        True,
    ),
    Integration(
        "frigate",
        "Frigate cameras",
        "Camera feeds and events from your Frigate server.",
        False,
        True,
    ),
)
BY_ID = {i.id: i for i in INTEGRATIONS}


def _rows(db: Session, home_id: str) -> dict[str, HomeIntegration]:
    rows = db.scalars(select(HomeIntegration).where(HomeIntegration.home_id == home_id))
    return {r.integration: r for r in rows}


def _out(integration: Integration, row: HomeIntegration | None) -> dict[str, Any]:
    return {
        "id": integration.id,
        "name": integration.name,
        "description": integration.description,
        "enabled": row.enabled if row else integration.default_enabled,
        "available": integration.available,
    }


def list_integrations(db: Session, home_id: str) -> list[dict[str, Any]]:
    rows = _rows(db, home_id)
    return [_out(i, rows.get(i.id)) for i in INTEGRATIONS]


def integration_enabled(db: Session, home_id: str, integration_id: str) -> bool:
    integration = BY_ID.get(integration_id)
    if integration is None:
        return False
    row = _rows(db, home_id).get(integration_id)
    return row.enabled if row else integration.default_enabled


def set_integration(
    db: Session,
    home_id: str,
    integration_id: str,
    enabled: bool,
    user_id: str | None,
    ip_address: str | None,
) -> dict[str, Any]:
    """Turn one integration on or off for a home, and audit it."""
    integration = BY_ID[integration_id]
    row = _rows(db, home_id).get(integration_id)
    if row is None:
        row = HomeIntegration(home_id=home_id, integration=integration_id)
        db.add(row)
    row.enabled = enabled
    db.commit()
    record_event(
        db,
        "integration_toggled",
        user_id=user_id,
        home_id=home_id,
        ip_address=ip_address,
        details={"integration": integration_id, "enabled": enabled},
    )
    return _out(integration, row)

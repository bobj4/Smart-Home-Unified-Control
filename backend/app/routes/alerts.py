"""Alerts (see app/alerts.py): the home's settings (admins), each person's
choices, and the browsers that take their notifications."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import alerts, device_alerts, webpush
from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.models import Device, PushSubscription, Role, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/alerts", tags=["alerts"])
push_router = APIRouter(prefix="/api/v1/account/push", tags=["alerts"])

Kind = Literal[
    "garage_open",
    "auto_close",
    "obstruction",
    "offline",
    "water_heater",
    "temperature",
    "camera",
    "smartthings",
    "filter",
]


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frigate_labels: list[str] | None = Field(default=None, max_length=10)


class DeviceAlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    settings: dict[str, Any] | None = None


class PrefsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: StrictBool | None = None
    push: StrictBool | None = None
    kinds: list[Kind] | None = Field(default=None, max_length=6)


class Keys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(min_length=80, max_length=200, pattern=r"^[A-Za-z0-9_-]+=*$")
    auth: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+=*$")


class SubscriptionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")  # browsers add expirationTime
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: Keys
    label: str | None = Field(default=None, max_length=100)


class EndpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get("")
def overview(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    member = require_role(db, user.id, home_id)
    row = alerts.settings_for(db, home_id)
    db.commit()
    mine = alerts.prefs_for(db, user.id, home_id)
    devices = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all()
    return {
        "settings": alerts.settings_out(row),
        "mine": alerts.prefs_out(mine),
        "kinds": [{"id": k, "label": v} for k, v in alerts.KINDS.items()],
        "email_available": alerts.email_available(db),
        "push_available": alerts.push_key(db, make=False) is not None or _vault_ok(),
        "push_devices": [{"label": d.label, "endpoint": d.endpoint} for d in devices],
        "can_admin": member.role == Role.ADMIN.value,
    }


def _vault_ok() -> bool:
    from app import vault

    try:
        vault.encrypt({"check": True})
    except vault.VaultError:
        return False
    return True


@router.put("/settings", dependencies=[Depends(require_csrf)])
def change_settings(
    home_id: str,
    body: SettingsIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id, Role.ADMIN)
    changes = body.model_dump(exclude_none=True)
    row = alerts.save_settings(db, home_id, changes)
    record_event(
        db,
        "alert_settings_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details=changes,
    )
    return alerts.settings_out(row)


@router.get("/devices")
def device_alerts_list(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, dict[str, Any]]:
    """Each device's alerts (the bells in Settings > Devices)."""
    require_role(db, user.id, home_id)
    return device_alerts.for_home(db, home_id)


@router.put("/devices/{device_id}", dependencies=[Depends(require_csrf)])
def change_device_alerts(
    home_id: str,
    device_id: str,
    body: DeviceAlertIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A device's alerts on or off, and its own alert settings (operators
    and up, as for the rest of Settings > Devices)."""
    require_role(db, user.id, home_id, Role.OPERATOR)
    device = db.get(Device, device_id)
    if device is None or device.home_id != home_id:
        raise HTTPException(404, "Not found")
    try:
        out = device_alerts.save(db, device, body.enabled, body.settings)
    except device_alerts.DeviceAlertError as error:
        db.rollback()
        raise HTTPException(422, error.reason) from None
    record_event(
        db,
        "device_alerts_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"device_id": device_id, **out},
    )
    return out


@router.put("/mine", dependencies=[Depends(require_csrf)])
def change_mine(
    home_id: str,
    body: PrefsIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_role(db, user.id, home_id)
    row = alerts.save_prefs(db, user.id, home_id, body.model_dump(exclude_none=True))
    return alerts.prefs_out(row)


@router.post("/test", dependencies=[Depends(require_csrf)])
def send_test(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """A test alert to me, by the ways I chose."""
    require_role(db, user.id, home_id)
    prefs = alerts.prefs_for(db, user.id, home_id)
    if not prefs.email and not prefs.push:
        raise HTTPException(422, "turn on email or notifications first")
    return alerts.send_to(
        db,
        user,
        prefs,
        "Test alert",
        "Alerts from your smart home reach you here.",
        "test",
    )


@router.get("/feed")
def bell(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """The bell at the top: the newest alerts and how many are new to me."""
    require_role(db, user.id, home_id)
    return alerts.feed(db, user.id, home_id)


@router.post("/feed/seen", dependencies=[Depends(require_csrf)])
def bell_seen(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, int]:
    require_role(db, user.id, home_id)
    alerts.mark_seen(db, user.id, home_id)
    return {"unseen": 0}


@router.delete("/feed", dependencies=[Depends(require_csrf)])
def bell_dismiss_all(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Clear my bell (others still see the alerts)."""
    require_role(db, user.id, home_id)
    alerts.dismiss_all(db, user.id, home_id)
    return alerts.feed(db, user.id, home_id)


@router.delete("/feed/{item_id}", dependencies=[Depends(require_csrf)])
def bell_dismiss(
    home_id: str,
    item_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Take one alert off my bell (others still see it)."""
    require_role(db, user.id, home_id)
    if not alerts.dismiss(db, user.id, home_id, item_id):
        raise HTTPException(404, "That alert is gone")
    return alerts.feed(db, user.id, home_id)


# ------------------------------------------------------------ this browser


@push_router.get("/key")
def push_key(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str | None]:
    """The key browsers subscribe with; None without SECRETS_KEY."""
    pem = alerts.push_key(db)
    return {"key": webpush.public_key(pem) if pem else None}


@push_router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def add_browser(
    body: SubscriptionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not alerts.push_host_allowed(body.endpoint):
        raise HTTPException(422, "not a browser push service")
    for value, size in ((body.keys.p256dh, 65), (body.keys.auth, 16)):
        try:
            ok = len(webpush.unb64url(value.rstrip("="))) == size
        except ValueError:
            ok = False
        if not ok:
            raise HTTPException(422, "not a browser's push keys")
    existing = db.scalars(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).first()
    if existing is not None:
        db.delete(existing)
        db.flush()
    db.add(
        PushSubscription(
            user_id=user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh.rstrip("="),
            auth=body.keys.auth.rstrip("="),
            label=body.label,
        )
    )
    db.commit()
    return {"detail": "Notifications on"}


@push_router.post("/remove", dependencies=[Depends(require_csrf)])
def remove_browser(
    body: EndpointIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    found = db.scalars(
        select(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint,
            PushSubscription.user_id == user.id,
        )
    ).first()
    if found is not None:
        db.delete(found)
        db.commit()
    return {"detail": "Notifications off on this device"}

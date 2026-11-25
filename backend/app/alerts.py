"""Alerts: the server watches for things worth knowing and tells the people
who asked, by email (the email server in Admin) and by notifications on
their phones and computers (Web Push, see app/webpush.py).

What it watches (each device's bell in Settings > Devices sets its own,
see app/device_alerts.py; camera labels are in Integrations > Frigate):
  garage_open   a garage door open longer than its open_minutes
  auto_close    and closes it after auto_close_minutes (0: never)
  obstruction   a ratgdo's obstruction sensor sees something in the way
  offline       a device offline longer than its offline_minutes
  water_heater  a water heater reports a new alert (Rheem EcoNet)
  temperature   a thermostat reads below too_cold or above too_hot
  camera        Frigate sees one of frigate_labels (a person, say)

Each person picks the kinds they want and how (My Account > Alerts):
nothing is sent until they do. One alert per episode: a door left open
alerts once until it closes again. What is being watched lives in memory,
so a restart starts each clock again.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import device_alerts, filter_reminders, mailer, vault, webpush
from app.audit import record_event
from app.db_config import SessionLocal
from app.features import integration_enabled
from app.login_policy import settings as system_settings
from app.models import (
    GUEST_ROLE,
    AlertDismissed,
    AlertItem,
    AlertPrefs,
    AlertSeen,
    AlertSettings,
    Device,
    Home,
    HomeMembership,
    PushSubscription,
    ServerKey,
    User,
    utcnow,
)

log = logging.getLogger(__name__)
TICK_SECONDS = 30
KINDS = {
    "garage_open": "A garage door is left open",
    "auto_close": "A garage door was closed for you",
    "obstruction": "Something is in a garage door's way",
    "offline": "A device stopped answering",
    "water_heater": "The water heater reports a problem",
    "temperature": "A thermostat reads too hot or too cold",
    "camera": "A camera sees someone",
    "smartthings": "SmartThings needs a new token or sign-in (TV inputs, turning TVs on)",
    "filter": "A thermostat's air filter needs changing",
}
PUSH_KEY = "webpush"
# Push services browsers use; nothing else is ever sent a notification.
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    "push.apple.com",
    "notify.windows.com",
)


# ------------------------------------------------------------ settings


def settings_for(db: Session, home_id: str) -> AlertSettings:
    row = db.get(AlertSettings, home_id)
    if row is None:
        row = AlertSettings(home_id=home_id, frigate_labels="person")
        db.add(row)
        db.flush()
    return row


def settings_out(row: AlertSettings) -> dict[str, Any]:
    return {"frigate_labels": [x for x in row.frigate_labels.split(",") if x]}


def save_settings(db: Session, home_id: str, changes: dict[str, Any]) -> AlertSettings:
    row = settings_for(db, home_id)
    if "frigate_labels" in changes:
        labels = [str(x).strip().lower() for x in changes["frigate_labels"]]
        row.frigate_labels = ",".join(x for x in labels if x)[:200]
    db.commit()
    return row


def prefs_for(db: Session, user_id: str, home_id: str) -> AlertPrefs:
    row = db.get(AlertPrefs, (user_id, home_id))
    if row is None:
        row = AlertPrefs(
            user_id=user_id, home_id=home_id, email=False, push=False, kinds="[]"
        )
    return row


def prefs_out(row: AlertPrefs) -> dict[str, Any]:
    return {
        "email": bool(row.email),
        "push": bool(row.push),
        "kinds": json.loads(row.kinds or "[]"),
    }


def save_prefs(
    db: Session, user_id: str, home_id: str, changes: dict[str, Any]
) -> AlertPrefs:
    row = prefs_for(db, user_id, home_id)
    if "email" in changes:
        row.email = bool(changes["email"])
    if "push" in changes:
        row.push = bool(changes["push"])
    if "kinds" in changes:
        row.kinds = json.dumps([k for k in KINDS if k in changes["kinds"]])
    db.merge(row)
    db.commit()
    return prefs_for(db, user_id, home_id)


# ------------------------------------------------------------ push


def push_key(db: Session, make: bool = True) -> str | None:
    """This server's push key (PEM), made once; None without SECRETS_KEY."""
    saved = db.get(ServerKey, PUSH_KEY)
    try:
        if saved is not None:
            return str(vault.decrypt(saved.value)["pem"])
        if not make:
            return None
        pem = webpush.new_key()
        db.add(ServerKey(name=PUSH_KEY, value=vault.encrypt({"pem": pem})))
        db.commit()
        return pem
    except vault.VaultError:
        return None


def push_host_allowed(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == known or host.endswith(f".{known}") for known in PUSH_HOSTS
    )


def email_available(db: Session) -> bool:
    return mailer.configured(system_settings(db))


# ------------------------------------------------------------ sending


def _send_push(
    db: Session, pem: str, sub: PushSubscription, message: dict[str, Any]
) -> bool:
    try:
        webpush.send(
            pem,
            {"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth},
            message,
        )
    except webpush.PushGone:
        db.delete(sub)
        db.commit()
        return False
    except webpush.PushError as error:
        log.info("a push notification was not sent: %s", error)
        return False
    return True


def send_to(
    db: Session, user: User, prefs: AlertPrefs, title: str, body: str, tag: str
) -> dict[str, Any]:
    """One person's alert, by the ways they chose."""
    sent: dict[str, Any] = {"email": False, "push": 0}
    if prefs.email and "@" in user.email and email_available(db):
        try:
            mailer.send_for(db, user.email, f"Smart home: {title}", body)
            sent["email"] = True
        except (mailer.MailError, vault.VaultError) as error:
            log.info("an alert email was not sent: %s", error)
    if prefs.push:
        pem = push_key(db, make=False)
        if pem:
            message = {"title": title, "body": body, "tag": tag, "url": "/#/devices"}
            for sub in list(
                db.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == user.id)
                )
            ):
                sent["push"] += int(_send_push(db, pem, sub, message))
    return sent


KEEP_ALERTS = 200  # the newest kept per home, for the bell


def remember(db: Session, home_id: str, kind: str, title: str, body: str) -> None:
    """Keep the alert for the bell (everyone in the home sees it there)."""
    db.add(AlertItem(home_id=home_id, kind=kind, title=title[:200], body=body[:500]))
    db.flush()
    old = db.scalars(
        select(AlertItem.id)
        .where(AlertItem.home_id == home_id)
        .order_by(AlertItem.id.desc())
        .offset(KEEP_ALERTS)
    ).all()
    if old:
        db.execute(delete(AlertDismissed).where(AlertDismissed.item_id.in_(old)))
        db.execute(delete(AlertItem).where(AlertItem.id.in_(old)))
    db.commit()


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def feed(db: Session, user_id: str, home_id: str, limit: int = 30) -> dict[str, Any]:
    """The bell: the newest alerts, and how many came since last opened."""
    seen = db.get(AlertSeen, (user_id, home_id))
    since = _aware(seen.seen_at) if seen else None
    dismissed = select(AlertDismissed.item_id).where(AlertDismissed.user_id == user_id)
    mine = (AlertItem.home_id == home_id) & AlertItem.id.not_in(dismissed)
    items = db.scalars(
        select(AlertItem).where(mine).order_by(AlertItem.id.desc()).limit(limit)
    ).all()
    unseen = select(func.count(AlertItem.id)).where(mine)
    if since is not None:
        unseen = unseen.where(AlertItem.created_at > since)
    # Filters due: first, counted until changed, and not dismissed.
    standing = filter_reminders.notices(db, home_id)
    return {
        "unseen": int(db.scalar(unseen) or 0) + len(standing),
        "items": standing
        + [
            {
                "id": i.id,
                "kind": i.kind,
                "title": i.title,
                "body": i.body,
                "at": _aware(i.created_at).isoformat(),
                "new": since is None or _aware(i.created_at) > since,
            }
            for i in items
        ],
    }


def dismiss(db: Session, user_id: str, home_id: str, item_id: int) -> bool:
    """Take an alert off this person's bell; False if the home has no such
    alert (already gone)."""
    item = db.get(AlertItem, item_id)
    if item is None or item.home_id != home_id:
        return False
    if db.get(AlertDismissed, (user_id, item_id)) is None:
        db.add(AlertDismissed(user_id=user_id, item_id=item_id))
        db.commit()
    return True


def dismiss_all(db: Session, user_id: str, home_id: str) -> int:
    """Take every alert the home has now off this person's bell; returns how
    many. Later alerts still show."""
    dismissed = select(AlertDismissed.item_id).where(AlertDismissed.user_id == user_id)
    ids = db.scalars(
        select(AlertItem.id).where(
            AlertItem.home_id == home_id, AlertItem.id.not_in(dismissed)
        )
    ).all()
    db.add_all(AlertDismissed(user_id=user_id, item_id=i) for i in ids)
    db.commit()
    return len(ids)


def mark_seen(db: Session, user_id: str, home_id: str) -> None:
    row = db.get(AlertSeen, (user_id, home_id))
    if row is None:
        db.add(AlertSeen(user_id=user_id, home_id=home_id, seen_at=utcnow()))
    else:
        row.seen_at = utcnow()
    db.commit()


def deliver(
    db: Session,
    home_id: str,
    kind: str,
    title: str,
    body: str,
    tag: str,
    keep: bool = True,
) -> int:
    """Keep the alert for the bell (unless keep is False: the bell shows it
    another way), and send it to everyone in the home who wants this kind;
    returns how many it reached by email or notification."""
    if keep:
        remember(db, home_id, kind, title, body)
    reached = 0
    rows = db.execute(
        select(User, HomeMembership)
        .join(HomeMembership, HomeMembership.user_id == User.id)
        .where(HomeMembership.home_id == home_id, HomeMembership.role != GUEST_ROLE)
    ).all()
    for user, _member in rows:
        prefs = db.get(AlertPrefs, (user.id, home_id))
        if prefs is None or kind not in json.loads(prefs.kinds or "[]"):
            continue
        sent = send_to(db, user, prefs, title, body, tag)
        reached += int(bool(sent["email"] or sent["push"]))
    record_event(
        db,
        "alert_sent",
        home_id=home_id,
        details={"kind": kind, "title": title, "reached": reached},
    )
    return reached


# ------------------------------------------------------------ watching


@dataclass
class Watch:
    """What is being watched, in memory: when each condition began, and
    which episodes already alerted."""

    since: dict[tuple[str, str], float] = field(default_factory=dict)
    alerted: set[tuple[str, str]] = field(default_factory=set)
    heater_alerts: dict[str, int] = field(default_factory=dict)
    camera_seen: dict[str, float] = field(default_factory=dict)

    def condition(self, key: tuple[str, str], holds: bool, now: float) -> float:
        """How long the condition has held (0 when it does not); a new
        episode starts each time it begins again."""
        if not holds:
            self.since.pop(key, None)
            self.alerted.discard(key)
            return 0.0
        start = self.since.setdefault(key, now)
        return now - start

    def once(self, key: tuple[str, str]) -> bool:
        """True the first time in this episode."""
        if key in self.alerted:
            return False
        self.alerted.add(key)
        return True


WATCH = Watch()


def _home_name(db: Session, home_id: str) -> str:
    home = db.get(Home, home_id)
    return home.name if home else "Home"


def check_home(
    db: Session, home_id: str, now: float | None = None, watch: Watch = WATCH
) -> int:
    """Look at one home; returns how many alerts went out."""
    from app.routes.devices import CommandRejected, DeviceCommand, apply_command

    now = time.monotonic() if now is None else now
    row = settings_for(db, home_id)
    db.commit()
    where = _home_name(db, home_id)
    sent = 0
    devices = list(db.scalars(select(Device).where(Device.home_id == home_id)))
    configs = device_alerts.for_home(db, home_id)
    for device in devices:
        state = json.loads(device.state or "{}")
        cfg = configs[device.id]
        on, rules = cfg["enabled"], cfg["settings"]
        if device.type == "garage_door":
            open_for = watch.condition(
                (device.id, "open"), state.get("door") == "open", now
            )
            minutes = rules.get("open_minutes") or 0
            if (
                on
                and minutes
                and open_for >= minutes * 60
                and watch.once((device.id, "open"))
            ):
                sent += deliver(
                    db,
                    home_id,
                    "garage_open",
                    f"{device.name} is open",
                    f"{device.name} at {where} has been open for {int(open_for // 60)} minutes.",
                    f"open-{device.id}",
                )
            close_after = rules.get("auto_close_minutes") or 0
            if (
                on
                and close_after
                and open_for >= close_after * 60
                and watch.once((device.id, "auto_close"))
            ):
                try:
                    apply_command(
                        db,
                        device,
                        DeviceCommand(command="close"),
                        {"user_id": None, "home_id": home_id, "ip_address": None},
                    )
                    text = f"{device.name} at {where} was open {close_after} minutes, so it is closing."
                except CommandRejected as rejected:
                    db.rollback()
                    text = f"{device.name} at {where} was left open, but could not be closed: {rejected.reason}"
                sent += deliver(
                    db,
                    home_id,
                    "auto_close",
                    f"Closing {device.name}",
                    text,
                    f"close-{device.id}",
                )
            blocked = bool(state.get("obstruction"))
            watch.condition((device.id, "obstruction"), blocked, now)
            if (
                on
                and rules.get("obstruction")
                and blocked
                and watch.once((device.id, "obstruction"))
            ):
                sent += deliver(
                    db,
                    home_id,
                    "obstruction",
                    f"{device.name} is blocked",
                    f"Something is in the way of {device.name} at {where}.",
                    f"block-{device.id}",
                )
        # Offline: devices with settings say after how long; the rest use
        # the usual wait when their alert is on.
        offline = rules.get("offline_minutes", device_alerts.OFFLINE_MINUTES)
        gone_for = watch.condition((device.id, "offline"), not device.online, now)
        if (
            on
            and offline
            and gone_for >= offline * 60
            and watch.once((device.id, "offline"))
        ):
            sent += deliver(
                db,
                home_id,
                "offline",
                f"{device.name} is offline",
                f"{device.name} at {where} has not answered for {int(gone_for // 60)} minutes.",
                f"offline-{device.id}",
            )
        if device.type == "water_heater":
            count = int(state.get("alerts") or 0)
            before = watch.heater_alerts.get(device.id)
            watch.heater_alerts[device.id] = count
            if on and rules.get("problems") and before is not None and count > before:
                sent += deliver(
                    db,
                    home_id,
                    "water_heater",
                    f"{device.name} reports a problem",
                    f"{device.name} at {where} reports {count} alert{'s' if count != 1 else ''}. See the Rheem EcoNet app for details.",
                    f"heater-{device.id}",
                )
        if device.type == "thermostat":
            sent += _check_temperature(
                db, home_id, device, state, rules, on, where, now, watch
            )
    sent += _check_cameras(db, home_id, row, where, watch)
    sent += _check_smartthings(db, home_id, where, watch)
    sent += _check_filters(db, home_id, where)
    return sent


def _check_filters(db: Session, home_id: str, where: str) -> int:
    """A thermostat's air filter due: sent once (the bell keeps showing it
    until Changed Filter; filter_reminders.py)."""
    from app import thermostat_filter

    thermostat_filter.sync(db, home_id)  # a change made in the Cync app
    sent = 0
    for device, row, shown in filter_reminders.due(db, home_id):
        if row.notified:
            continue
        row.notified = True
        db.commit()
        when = filter_reminders.every_text(shown)
        sent += deliver(
            db,
            home_id,
            "filter",
            f"{device.name}: change the air filter",
            f"{where}: the air filter of {device.name} is due ({when}). "
            "Press Changed Filter in the app once it is replaced.",
            f"filter-{device.id}",
            keep=False,
        )
    return sent


def _check_smartthings(db: Session, home_id: str, where: str, watch: Watch) -> int:
    """A SmartThings token about to end (an hour before) or ended, or a
    sign-in that must be done again: once each time it happens."""
    from app import credentials, features, smartthings_oauth

    found = None
    if features.integration_enabled(db, home_id, "samsung_tv") and credentials.label(
        db, home_id, smartthings_oauth.CREDENTIAL
    ):
        try:
            saved = credentials.load(db, home_id, smartthings_oauth.CREDENTIAL)
        except vault.VaultError:
            saved = None
        found = smartthings_oauth.health(saved, time.time())
    sent = 0
    for state, title in (
        ("soon", "SmartThings token ends soon"),
        ("lapsed", "SmartThings needs connecting again"),
    ):
        key = (home_id, f"smartthings-{state}")
        holds = found is not None and found[0] == state
        watch.condition(key, holds, 0.0)
        if holds and found is not None and watch.once(key):
            sent += deliver(
                db, home_id, "smartthings", title, f"{where}: {found[1]}.", key[1]
            )
    return sent


def _check_temperature(
    db: Session,
    home_id: str,
    device: Device,
    state: dict[str, Any],
    rules: dict[str, Any],
    on: bool,
    where: str,
    now: float,
    watch: Watch,
) -> int:
    """A thermostat reading below too_cold or above too_hot, once per spell."""
    reading = state.get("current_temperature", state.get("temperature"))
    unit = state.get("unit") or "F"
    sent = 0
    for key, word, beyond in (
        ("too_cold", "cold", lambda r, t: r < t),
        ("too_hot", "hot", lambda r, t: r > t),
    ):
        limit = rules.get(key)
        holds = (
            on
            and limit is not None
            and isinstance(reading, int | float)
            and beyond(reading, limit)
        )
        watch.condition((device.id, key), bool(holds), now)
        if holds and watch.once((device.id, key)):
            sent += deliver(
                db,
                home_id,
                "temperature",
                f"{device.name} is too {word}",
                f"{device.name} at {where} reads {reading:g} °{unit} (alert at {limit} °{unit}).",
                f"{key}-{device.id}",
            )
    return sent


def _check_cameras(
    db: Session, home_id: str, row: AlertSettings, where: str, watch: Watch
) -> int:
    from app import frigate_home

    labels = {x for x in row.frigate_labels.split(",") if x}
    if not labels or not integration_enabled(db, home_id, "frigate"):
        return 0
    try:
        client = frigate_home.client_for_home(db, home_id)
        events = frigate_home.call(lambda: client.events(20))
    except frigate_home.FrigateUnavailable:
        return 0
    starts = [
        float(e["start_time"])
        for e in events
        if isinstance(e.get("start_time"), int | float)
    ]
    seen = watch.camera_seen.get(home_id)
    watch.camera_seen[home_id] = (
        max([seen or 0.0, *starts]) if starts else (seen or time.time())
    )
    if seen is None:
        return 0  # the first look: only events from now on
    fresh = [
        e
        for e in events
        if isinstance(e.get("start_time"), int | float)
        and float(e["start_time"]) > seen
        and e.get("label") in labels
    ]
    if not fresh:
        return 0
    first = fresh[0]
    more = f" (and {len(fresh) - 1} more)" if len(fresh) > 1 else ""
    camera = str(first.get("camera", "")).replace("_", " ")
    return deliver(
        db,
        home_id,
        "camera",
        f"{str(first['label']).capitalize()} at {camera}",
        f"The {camera} camera at {where} sees a {first['label']}{more}.",
        f"camera-{home_id}",
    )


def _tick() -> None:
    with SessionLocal() as db:
        for home_id in db.scalars(select(Home.id)).all():
            try:
                check_home(db, home_id)
            except Exception:  # one bad home must not stop the others
                db.rollback()
                log.exception("alerts: a check failed")


async def run_forever() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        await asyncio.to_thread(_tick)

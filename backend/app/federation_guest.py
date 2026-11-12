"""Guests of a home at another site (app/federation.py).

A guest's permissions are kept here on the main server, with the home's
people, so the main server applies them itself: it reads the home's devices
from the site, shows the guest only those they may use (the same checks as
app/guest_access.py), and sends on only the commands they may give. The
site runs those as a member, or as an admin for what the main server has
already checked (a thermostat's installer settings a guest is allowed).
"""

import json
from types import SimpleNamespace
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import federation
from app.audit import record_event
from app.db_config import SessionLocal
from app.dependencies import client_ip
from app.guest_access import access_out, allowed, can_see
from app.models import GuestAccess
from app.thermostat_setting_names import INSTALLER


def _json(data: Any, code: int = 200) -> Response:
    return JSONResponse(data, status_code=code)


async def _site(
    home_id: str, site_home: str, method: str, part: str, role: str, body: str = ""
) -> tuple[int, Any]:
    answer = await federation.forward(
        home_id,
        {
            "method": method,
            "path": f"/api/v1/homes/{site_home}/{part}",
            "query": "",
            "body": body,
            "role": role,
        },
    )
    try:
        data = json.loads(str(answer.get("body") or "null"))
    except ValueError:
        data = None
    return int(answer.get("status") or 502), data


def _as_device(found: dict[str, Any]) -> Any:
    """What the guest checks look at (type, id, integration)."""
    return SimpleNamespace(
        id=str(found.get("id")),
        type=found.get("type"),
        integration=found.get("integration"),
    )


async def _devices(home_id: str, site_home: str) -> list[dict[str, Any]]:
    code, data = await _site(home_id, site_home, "GET", "devices", "member")
    if code != 200 or not isinstance(data, list):
        raise federation.SiteOffline(federation.OFFLINE)
    return [d for d in data if isinstance(d, dict)]


async def page(home_id: str, site_home: str, access: GuestAccess) -> Response:
    devices = []
    for found in await _devices(home_id, site_home):
        if can_see(access, _as_device(found)):
            devices.append({k: v for k, v in found.items() if k != "network"})
        elif access.show_blocked:
            devices.append(
                {
                    "id": found.get("id"),
                    "name": found.get("name"),
                    "type": found.get("type"),
                    "room": found.get("room"),
                    "online": found.get("online"),
                    "state": {},
                    "blocked": True,
                }
            )
    _, limits = await _site(home_id, site_home, "GET", "safety-limits", "admin")
    _, integrations = await _site(home_id, site_home, "GET", "integrations", "admin")
    return _json(
        {
            "access": access_out(access),
            "devices": devices,
            "limits": limits if isinstance(limits, list) else [],
            "integrations_on": [
                i.get("id")
                for i in (integrations if isinstance(integrations, list) else [])
                if isinstance(i, dict) and i.get("enabled")
            ],
        }
    )


async def handle(
    request: Request, home_id: str, site_home: str, rest: str, access: GuestAccess
) -> Response:
    """/api/v1/homes/{id}/guest<rest> for a guest of a home at another site."""
    if rest in ("", "/") and request.method == "GET":
        return await page(home_id, site_home, access)
    parts = rest.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "devices":
        return _json({"detail": "Not found"}, 404)
    device_id, action = parts[1], parts[2]
    found = next(
        (
            d
            for d in await _devices(home_id, site_home)
            if str(d.get("id")) == device_id
        ),
        None,
    )
    device = _as_device(found) if found else None
    if device is None or not (can_see(access, device) or access.show_blocked):
        return _json({"detail": "Not found"}, 404)
    body = (await request.body()).decode("utf-8", "replace")
    who = {
        "user_id": access.user_id,
        "home_id": home_id,
        "ip_address": client_ip(request),
    }
    if action == "command" and request.method == "POST":
        command = str((json.loads(body or "{}") or {}).get("command", ""))
        if not allowed(access, device, command):
            with SessionLocal() as db:
                record_event(
                    db,
                    "guest_command_refused",
                    **who,
                    details={"device_id": device_id, "command": command},
                )
            return _json({"detail": "Guests cannot do that here"}, 403)
        code, data = await _site(
            home_id, site_home, "POST", f"devices/{device_id}/command", "member", body
        )
        return _json(data, code)
    if action == "settings" and request.method in ("GET", "PUT"):
        if device.type != "thermostat" or not can_see(access, device):
            return _json({"detail": "Not found"}, 404)
        if not access.thermostat_settings:
            return _json({"detail": "Guests cannot do that here"}, 403)
        role = "member"
        if request.method == "PUT":
            changes = json.loads(body or "{}") or {}
            if INSTALLER.intersection(changes):
                if not access.thermostat_installer:
                    return _json({"detail": "Guests cannot do that here"}, 403)
                role = "admin"  # allowed here; the site's own rule is for its people
        code, data = await _site(
            home_id,
            site_home,
            request.method,
            f"devices/{device_id}/settings",
            role,
            body,
        )
        if isinstance(data, dict) and code == 200:
            data["installer_allowed"] = bool(access.thermostat_installer)
        return _json(data, code)
    return _json({"detail": "Not found"}, 404)

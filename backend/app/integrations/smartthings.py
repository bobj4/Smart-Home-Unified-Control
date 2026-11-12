"""SmartThings cloud API, for what a Samsung TV only tells SmartThings: its
inputs by name (HDMI 1 = "PlayStation") and choosing one directly.

Uses a sign-in that renews itself (OAuth, app/smartthings_oauth.py) or a
personal access token (account.smartthings.com/tokens, 24 hours), with the
"devices" read and execute permissions. Tests replace these functions.
"""

from typing import Any
from urllib.parse import quote, urlencode

import requests

API = "https://api.smartthings.com/v1"
TIMEOUT_SECONDS = 10
# Samsung's own capability names its inputs; the standard one only lists ids.
SAMSUNG_INPUTS = "samsungvd.mediaInputSource"
STANDARD_INPUTS = "mediaInputSource"


class SmartThingsError(Exception):
    """SmartThings could not be reached or refused."""


class SmartThingsDenied(SmartThingsError):
    """The token is wrong, expired or lacks a permission."""


def _call(method: str, path: str, token: str, body: Any = None) -> Any:
    try:
        response = requests.request(
            method,
            f"{API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SmartThingsError(
            f"could not reach SmartThings: {type(error).__name__}"
        ) from None
    if response.status_code in (401, 403):
        raise SmartThingsDenied("SmartThings refused the token")
    if response.status_code >= 400:
        raise SmartThingsError(f"SmartThings answered {response.status_code}")
    return response.json() if response.content else None


def _capabilities(device: dict[str, Any]) -> set[str]:
    return {
        str(cap.get("id"))
        for component in device.get("components") or []
        for cap in component.get("capabilities") or []
    }


def tvs(token: str) -> list[dict[str, str]]:
    """The account's devices that can change input: [{"id", "name"}]."""
    found = _call("GET", "/devices", token) or {}
    out = []
    for device in found.get("items") or []:
        if _capabilities(device) & {SAMSUNG_INPUTS, STANDARD_INPUTS}:
            name = device.get("label") or device.get("name") or "TV"
            out.append({"id": str(device["deviceId"]), "name": str(name)})
    return sorted(out, key=lambda tv: tv["name"].lower())


def _value(status: dict[str, Any], capability: str, attribute: str) -> Any:
    return ((status.get(capability) or {}).get(attribute) or {}).get("value")


def sources(token: str, device_id: str) -> dict[str, Any]:
    """The TV's inputs and the current one:
    {"current": id or None, "sources": [{"id", "name"}]}."""
    status = _call("GET", f"/devices/{device_id}/components/main/status", token) or {}
    named = _value(status, SAMSUNG_INPUTS, "supportedInputSourcesMap")
    if named:
        found = [
            {"id": str(s["id"]), "name": str(s.get("name") or s["id"])}
            for s in named
            if isinstance(s, dict) and s.get("id")
        ]
        current = _value(status, SAMSUNG_INPUTS, "inputSource")
    else:
        ids = _value(status, STANDARD_INPUTS, "supportedInputSources") or []
        found = [{"id": str(i), "name": str(i)} for i in ids]
        current = _value(status, STANDARD_INPUTS, "inputSource")
    return {"current": current, "sources": found}


def set_source(token: str, device_id: str, source: str) -> None:
    status = _call("GET", f"/devices/{device_id}/components/main/status", token) or {}
    capability = SAMSUNG_INPUTS if SAMSUNG_INPUTS in status else STANDARD_INPUTS
    command = {
        "component": "main",
        "capability": capability,
        "command": "setInputSource",
        "arguments": [source],
    }
    _call("POST", f"/devices/{device_id}/commands", token, {"commands": [command]})


# ---------------------------------------------------------------- OAuth
# Personal access tokens made since late 2024 last 24 hours. An "OAuth-In"
# (API only) SmartApp gets a 24-hour access token plus a refresh token that
# swaps for a new pair (each refresh token works once; it lapses after about
# 29 days unused). See app/smartthings_oauth.py.

OAUTH = "https://api.smartthings.com/oauth"
SCOPES = "r:devices:* x:devices:*"


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
        },
        quote_via=quote,
    )
    return f"{OAUTH}/authorize?{query}"


def token_request(
    client_id: str, client_secret: str, form: dict[str, str]
) -> dict[str, Any]:
    """POST to the token endpoint (Basic auth with the app's ID and secret):
    {"access_token", "refresh_token", "expires_in", ...}."""
    try:
        response = requests.post(
            f"{OAUTH}/token",
            auth=(client_id, client_secret),
            data={**form, "client_id": client_id},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise SmartThingsError(
            f"could not reach SmartThings: {type(error).__name__}"
        ) from None
    if response.status_code in (400, 401, 403):
        raise SmartThingsDenied(
            "SmartThings refused the sign-in: connect SmartThings again"
        )
    if response.status_code >= 400:
        raise SmartThingsError(f"SmartThings answered {response.status_code}")
    try:
        answer = response.json()
    except ValueError:
        raise SmartThingsError("SmartThings answered with something else") from None
    if not isinstance(answer, dict) or not answer.get("access_token"):
        raise SmartThingsError("SmartThings gave no token")
    return answer

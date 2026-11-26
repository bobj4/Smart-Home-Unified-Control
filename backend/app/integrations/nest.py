"""Google Nest through Google's Device Access (the Smart Device Management
API): thermostats, and camera and doorbell events.

Device Access needs a one-time, non-refundable US$5 registration with
Google (console.nest.google.com/device-access), a Google Cloud OAuth client
("Web application", redirect https://www.google.com) and, for camera and
doorbell events, a Pub/Sub topic and pull subscription in that Google Cloud
project (Google-hosted topics end on 30 November 2026). See docs/NEST.md.

The person signs in on Google's Partner Connections page and pastes back
the address they land on; its code is swapped for an access token (one
hour) and a refresh token (kept while it is used). Tests replace these
functions.
"""

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

API = "https://smartdevicemanagement.googleapis.com/v1"
PUBSUB = "https://pubsub.googleapis.com/v1"
GRANT_URL = "https://www.googleapis.com/oauth2/v4/token"
AUTH_URL = "https://nestservices.google.com/partnerconnections/{project}/auth"
REDIRECT = "https://www.google.com"
SCOPES = (
    "https://www.googleapis.com/auth/sdm.service",
    "https://www.googleapis.com/auth/pubsub",  # camera and doorbell events
)
TIMEOUT_SECONDS = 15
TRAIT = "sdm.devices.traits."
COMMAND = "sdm.devices.commands."
EVENT = "sdm.devices.events."


class NestError(Exception):
    """Google could not be reached or refused."""


class NestDenied(NestError):
    """The sign-in is wrong, expired or was taken back (sign in again)."""


def authorize_url(project_id: str, client_id: str, state: str) -> str:
    """Google's page where the person picks the home and devices to share."""
    query = urlencode(
        {
            "redirect_uri": REDIRECT,
            "access_type": "offline",
            "prompt": "consent",
            "client_id": client_id,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
        }
    )
    return f"{AUTH_URL.format(project=project_id)}?{query}"


def code_from(pasted: str) -> tuple[str, str | None]:
    """(code, state) from the address the person landed on (or the bare code)."""
    text = pasted.strip()
    if "://" not in text and "code=" not in text:
        return text, None
    query = parse_qs(urlsplit(text).query or text.split("?", 1)[-1])
    if "error" in query:
        raise NestError(f"Google said: {query['error'][0]}")
    codes = query.get("code")
    if not codes:
        raise NestError("that address has no code= in it")
    states = query.get("state")
    return codes[0], states[0] if states else None


def _token(form: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(GRANT_URL, data=form, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise NestError(f"could not reach Google: {type(error).__name__}") from None
    try:
        answer = response.json()
    except ValueError:
        answer = {}
    if response.status_code in (400, 401):
        why = str(answer.get("error_description") or answer.get("error") or "")
        raise NestDenied(f"Google refused the sign-in{f': {why}' if why else ''}")
    if response.status_code >= 400 or "access_token" not in answer:
        raise NestError(f"Google answered {response.status_code}")
    return dict(answer)


def exchange(client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    """The sign-in's code -> {"access_token", "refresh_token", "expires_in"}."""
    return _token(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT,
        }
    )


def refresh(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    return _token(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )


def _call(method: str, url: str, token: str, body: Any = None) -> Any:
    try:
        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise NestError(f"could not reach Google: {type(error).__name__}") from None
    try:
        answer = response.json() if response.content else {}
    except ValueError:
        answer = {}
    if response.status_code == 401:
        raise NestDenied("Google no longer accepts the sign-in")
    if response.status_code >= 400:
        message = (answer.get("error") or {}).get("message") if answer else None
        if response.status_code == 429:
            message = "Google is limiting requests for now (too many): try again soon"
        raise NestError(message or f"Google answered {response.status_code}")
    return answer


def list_devices(token: str, project_id: str) -> list[dict[str, Any]]:
    answer = _call("GET", f"{API}/enterprises/{project_id}/devices", token)
    return list(answer.get("devices") or [])


def execute(token: str, device_name: str, command: str, params: dict[str, Any]) -> None:
    """One command, e.g. ThermostatMode.SetMode with {"mode": "HEAT"}."""
    _call(
        "POST",
        f"{API}/{device_name}:executeCommand",
        token,
        {"command": f"{COMMAND}{command}", "params": params},
    )


def pull(token: str, subscription: str, most: int = 50) -> list[dict[str, Any]]:
    """Waiting events from the Pub/Sub subscription ("projects/../subscriptions/..")
    as [{"ack_id", "event"}] (event: the decoded SDM message)."""
    answer = _call(
        "POST",
        f"{PUBSUB}/{subscription}:pull",
        token,
        {"maxMessages": most, "returnImmediately": True},
    )
    found = []
    for received in answer.get("receivedMessages") or []:
        data = (received.get("message") or {}).get("data") or ""
        try:
            event = json.loads(base64.b64decode(data))
        except ValueError:
            event = {}
        found.append({"ack_id": received.get("ackId"), "event": event})
    return found


def acknowledge(token: str, subscription: str, ack_ids: list[str]) -> None:
    if ack_ids:
        _call(
            "POST", f"{PUBSUB}/{subscription}:acknowledge", token, {"ackIds": ack_ids}
        )

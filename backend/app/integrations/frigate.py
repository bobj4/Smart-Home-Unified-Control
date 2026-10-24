"""Frigate NVR (0.14 and newer) on this machine or the home network.

`connect(...)` is the only way the app talks to Frigate; tests replace it
with a fake. With a username, the client logs in at POST /api/login (the
authenticated port, usually https://<host>:8971) and keeps Frigate's session
cookie in memory, reusing it until Frigate answers 401. Without a username it
uses the unauthenticated port (usually http://<host>:5000).
"""

import hashlib
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests

TIMEOUT_SECONDS = 10
SESSION_SECONDS = 12 * 3600
CHUNK = 64 * 1024
# hash of (url, username, password) -> (requests session, time of login)
_sessions: dict[str, tuple[requests.Session, float]] = {}


class FrigateError(Exception):
    """Frigate could not be reached or answered with an error."""


class FrigateLoginError(FrigateError):
    """Frigate refused the username or password."""


class FrigateNotFound(FrigateError):
    """No such event, or it has no clip or thumbnail."""


@dataclass(frozen=True)
class Media:
    """A thumbnail or a (part of a) clip to pass on to the browser."""

    status_code: int
    content_type: str
    headers: dict[str, str]
    body: Iterator[bytes]


def event_out(event: dict[str, Any]) -> dict[str, Any]:
    """The fields of a Frigate event the app shows."""
    data = event.get("data") or {}
    score = data.get("top_score", event.get("top_score"))
    return {
        "id": str(event["id"]),
        "camera": str(event.get("camera", "")),
        "label": str(event.get("label", "")),
        "sub_label": event.get("sub_label")
        if isinstance(event.get("sub_label"), str)
        else None,
        "score": round(float(score), 2) if isinstance(score, int | float) else None,
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time"),
        "has_clip": bool(event.get("has_clip")),
        "has_snapshot": bool(event.get("has_snapshot")),
    }


class FrigateClient:
    def __init__(
        self, url: str, username: str | None, password: str | None, verify_tls: bool
    ) -> None:
        self._url = url.rstrip("/")
        self._username = username or None
        self._password = password or ""
        self._verify = verify_tls

    # ------------------------------------------------------------ session

    def _key(self) -> str:
        raw = f"{self._url}\0{self._username or ''}\0{self._password}\0{self._verify}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _session(self, fresh: bool = False) -> requests.Session:
        key = self._key()
        saved = _sessions.get(key)
        if not fresh and saved and time.monotonic() - saved[1] < SESSION_SECONDS:
            return saved[0]
        session = requests.Session()
        session.verify = self._verify
        if self._username:
            try:
                response = session.post(
                    f"{self._url}/api/login",
                    json={"user": self._username, "password": self._password},
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as error:
                raise FrigateError(
                    f"could not reach Frigate: {type(error).__name__}"
                ) from None
            if response.status_code in (400, 401, 403):
                raise FrigateLoginError("Frigate refused the username or password")
            if response.status_code == 429:
                raise FrigateError("Frigate is limiting logins; wait a few minutes")
            if response.status_code != 200:
                raise FrigateError(f"Frigate login failed: HTTP {response.status_code}")
        _sessions[key] = (session, time.monotonic())
        return session

    def _get(self, path: str, stream: bool = False, **kwargs: Any) -> requests.Response:
        for attempt in (0, 1):
            session = self._session(fresh=attempt == 1)
            try:
                response = session.get(
                    f"{self._url}{path}",
                    timeout=TIMEOUT_SECONDS,
                    stream=stream,
                    **kwargs,
                )
            except requests.RequestException as error:
                raise FrigateError(
                    f"could not reach Frigate: {type(error).__name__}"
                ) from None
            if response.status_code == 401 and self._username and attempt == 0:
                response.close()
                continue  # the saved login expired: log in again once
            if response.status_code in (401, 403):
                response.close()
                raise FrigateLoginError("Frigate refused the saved login")
            if response.status_code == 404:
                response.close()
                raise FrigateNotFound("not found in Frigate")
            if response.status_code >= 400:
                response.close()
                raise FrigateError(f"Frigate answered HTTP {response.status_code}")
            return response
        raise FrigateError("Frigate refused the saved login")  # pragma: no cover

    def _json(self, path: str, **params: Any) -> Any:
        response = self._get(path, params=params or None)
        try:
            return response.json()
        except ValueError:
            raise FrigateError("Frigate sent something that is not JSON") from None

    # ------------------------------------------------------------ the interface

    def cameras(self) -> list[str]:
        config = self._json("/api/config")
        cameras = config.get("cameras") if isinstance(config, dict) else None
        if not isinstance(cameras, dict):
            raise FrigateError("Frigate sent an unexpected configuration")
        return sorted(str(name) for name in cameras)

    def events(self, limit: int, camera: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "include_thumbnails": 0}
        if camera:
            params["cameras"] = camera
        events = self._json("/api/events", **params)
        if not isinstance(events, list):
            raise FrigateError("Frigate sent an unexpected event list")
        return [event_out(e) for e in events if isinstance(e, dict) and "id" in e]

    def thumbnail(self, event_id: str) -> Media:
        response = self._get(f"/api/events/{event_id}/thumbnail.jpg")
        return Media(
            200,
            response.headers.get("Content-Type", "image/jpeg"),
            {},
            iter([response.content]),
        )

    def clip(self, event_id: str, byte_range: str | None) -> Media:
        headers = {"Range": byte_range} if byte_range else {}
        response = self._get(
            f"/api/events/{event_id}/clip.mp4", stream=True, headers=headers
        )
        passed = {
            name: response.headers[name]
            for name in ("Content-Length", "Content-Range", "Accept-Ranges")
            if name in response.headers
        }

        def body() -> Iterator[bytes]:
            try:
                yield from response.iter_content(CHUNK)
            finally:
                response.close()

        return Media(response.status_code, "video/mp4", passed, body())


def connect(
    url: str, username: str | None, password: str | None, verify_tls: bool
) -> FrigateClient:
    return FrigateClient(url, username, password, verify_tls)

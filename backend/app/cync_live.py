"""Live Cync state: while the server runs, each home with Cync turned on and
a saved login keeps one connection to Cync open and stores state reports as
they arrive, so the app shows changes made anywhere within seconds."""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app import credentials, cync_home
from app.db_config import SessionLocal
from app.features import integration_enabled
from app.integrations import cync
from app.models import Home
from app.vault import VaultError

CHECK_SECONDS = 60  # how often to look for homes to start or stop
RETRY_SECONDS = 30  # after a dropped or failed connection
log = logging.getLogger(__name__)
_listeners: dict[str, asyncio.Task[None]] = {}
# home id -> (open pycync connection, its event loop), while connected
_open: dict[str, tuple[Any, asyncio.AbstractEventLoop]] = {}


def connection(home_id: str) -> tuple[Any, asyncio.AbstractEventLoop] | None:
    """The live connection for a home, if one is open (for commands)."""
    return _open.get(home_id)


def wanted_homes() -> dict[str, dict[str, Any]]:
    """Home id -> saved Cync tokens, for homes that should be listening."""
    found: dict[str, dict[str, Any]] = {}
    with SessionLocal() as db:
        for home_id in db.scalars(select(Home.id)).all():
            if not integration_enabled(db, home_id, cync_home.INTEGRATION):
                continue
            try:
                saved = credentials.load(db, home_id, cync_home.INTEGRATION)
            except VaultError:
                continue
            if saved and saved.get("tokens"):
                found[home_id] = saved["tokens"]
    return found


def _store(home_id: str, states: dict[str, dict[str, Any]]) -> None:
    with SessionLocal() as db:
        cync_home.store_states(db, home_id, states)


async def _listen(home_id: str, tokens: dict[str, Any]) -> None:
    async def on_states(states: dict[str, dict[str, Any]]) -> None:
        await asyncio.to_thread(_store, home_id, states)

    loop = asyncio.get_running_loop()

    def on_open(api: Any) -> None:
        _open[home_id] = (api, loop)

    while True:
        try:
            await cync.listen(tokens, on_states, on_open=on_open)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # reconnect later; never stop the server
            log.info("Cync live connection ended: %s", type(error).__name__)
        finally:
            _open.pop(home_id, None)
        await asyncio.sleep(RETRY_SECONDS)


async def check_once() -> None:
    wanted = await asyncio.to_thread(wanted_homes)
    for home_id in list(_listeners):
        if home_id not in wanted or _listeners[home_id].done():
            _listeners.pop(home_id).cancel()
    for home_id, tokens in wanted.items():
        if home_id not in _listeners:
            _listeners[home_id] = asyncio.create_task(_listen(home_id, tokens))


async def run_forever() -> None:
    try:
        while True:
            await check_once()
            await asyncio.sleep(CHECK_SECONDS)
    finally:
        for task in _listeners.values():
            task.cancel()
        _listeners.clear()

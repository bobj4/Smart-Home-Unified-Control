"""Reading many devices at once for the background refresh, and asking
less often about ones that keep not answering.

Each unreachable device used to cost its whole timeout, one after another
(a Kasa plug up to 10 seconds, a ratgdo or Roku 5), so a few offline
devices pushed a pass past its 30 seconds and every state lagged. Now the
network reads of one integration run side by side (gather; the database is
only touched by the caller, on its own thread), and a device that has
missed twice in a row is asked again only after BACKOFF seconds (due).
Commands sent from the app are not affected: they always try at once.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

MAX_WORKERS = 8
# Wait after 2, 3, 4 and more misses in a row (the first miss is retried).
BACKOFF = (60.0, 120.0, 300.0)
# key -> (misses in a row, when it is next due)
_misses: dict[str, tuple[int, float]] = {}


def due(key: str, now: float | None = None) -> bool:
    """Whether to read this device on this pass."""
    entry = _misses.get(key)
    now = time.monotonic() if now is None else now
    return entry is None or now >= entry[1]


def answered(key: str, ok: bool, now: float | None = None) -> None:
    """Note whether the device answered."""
    if ok:
        _misses.pop(key, None)
        return
    now = time.monotonic() if now is None else now
    misses = _misses.get(key, (0, 0.0))[0] + 1
    wait = 0.0 if misses < 2 else BACKOFF[min(misses - 2, len(BACKOFF) - 1)]
    _misses[key] = (misses, now + wait)


def gather(reads: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    """Run each read side by side; its result, or the exception it raised."""
    if not reads:
        return {}

    def run(read: Callable[[], Any]) -> Any:
        try:
            return read()
        except Exception as error:  # noqa: BLE001 - handed back to the caller
            return error

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(reads))) as pool:
        futures = {key: pool.submit(run, read) for key, read in reads.items()}
        return {key: future.result() for key, future in futures.items()}

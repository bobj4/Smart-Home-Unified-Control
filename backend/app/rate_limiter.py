"""Login rate limiting (SEC-05, H1).

Failed attempts are counted per account and per client address over a
sliding window. While either limit is reached, login answers 429, even
with the right password. Counts are kept in memory, so run one worker.
"""

import time
from collections import defaultdict

from fastapi import HTTPException, status

WINDOW_SECONDS = 300
MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_ADDRESS = 20

_failures: defaultdict[tuple[str, str], list[float]] = defaultdict(list)


def _recent(key: tuple[str, str]) -> list[float]:
    cutoff = time.monotonic() - WINDOW_SECONDS
    _failures[key] = [t for t in _failures[key] if t > cutoff]
    return _failures[key]


def check_login_allowed(account: str, address: str | None) -> None:
    """Raise 429 if this account or address has too many recent failures."""
    if (
        len(_recent(("account", account))) >= MAX_FAILURES_PER_ACCOUNT
        or len(_recent(("address", address or ""))) >= MAX_FAILURES_PER_ADDRESS
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )


def record_login_failure(account: str, address: str | None) -> None:
    now = time.monotonic()
    _failures[("account", account)].append(now)
    _failures[("address", address or "")].append(now)


def reset_rate_limits() -> None:
    """Clear all counters. Used by the tests."""
    _failures.clear()

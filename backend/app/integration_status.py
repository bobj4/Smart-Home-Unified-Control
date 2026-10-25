"""The last connection problem of each home's integrations, shown in
Settings > Integrations: a saved login that stopped working, or a server that
stopped answering, is otherwise only visible in the server log.

Kept in memory: it is about the last few minutes, and a restart re-checks.
"""

from datetime import UTC, datetime
from typing import Any

_problems: dict[tuple[str, str], tuple[str, datetime]] = {}


def failed(home_id: str, integration: str, reason: str) -> None:
    _problems[(home_id, integration)] = (reason, datetime.now(UTC))


def worked(home_id: str, integration: str) -> None:
    _problems.pop((home_id, integration), None)


def for_home(home_id: str) -> dict[str, dict[str, Any]]:
    return {
        integration: {"reason": reason, "at": at.isoformat()}
        for (home, integration), (reason, at) in _problems.items()
        if home == home_id
    }


def clear() -> None:  # tests
    _problems.clear()

"""The apps on a Samsung TV that will not list them.

Many 2020+ TVs ignore the "installed apps" request (samsungtvws: "not
available on all TVs"), so the app asks instead about well-known apps one
by one: GET /api/v2/applications/<app id> answers for an installed app
(with its name) and 404s for one that is not. Older firmware answers on
http port 8001; newer firmware only on https port 8002 (the TV's own
self-signed certificate, the port the app pairs and launches apps on).
A TV that answers neither way gets the common apps to choose from
(common()): one it does not have simply does not open.
"""

import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

ASK_SECONDS = 2.5
# Samsung's store ids of well-known apps (an id the TV does not have just
# answers 404). Some apps have had more than one id: the first is the one
# offered when the TV will not say (common()).
KNOWN = {
    "3201907018807": "Netflix",
    "11101200001": "Netflix",
    "111299001912": "YouTube",
    "3201707014489": "YouTube TV",
    "3201910019365": "Prime Video",
    "3201512006785": "Prime Video",
    "3201901017640": "Disney+",
    "3201601007625": "Hulu",
    "3201606009684": "Spotify",
    "3201807016597": "Apple TV",
    "3202301029760": "Max",
    "3201601007230": "HBO Max",
    "3201512006963": "Plex",
    "3201710014981": "Paramount+",
    "3202006020991": "Peacock",
    "3201504001965": "Tubi",
    "3201808016802": "Pluto TV",
    "3202203026841": "Twitch",
    "111012010001": "Vudu",
    "org.tizen.browser": "Internet",
}
WAYS = ("http://{host}:8001", "https://{host}:8002")


def _ask(base: str, app_id: str) -> dict[str, str] | None:
    try:
        response = requests.get(
            f"{base}/api/v2/applications/{app_id}",
            timeout=ASK_SECONDS,
            # The TV's certificate is self-signed (no authority to check it
            # against); this only asks whether an app is installed.
            verify=False,  # nosec B501
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        info: Any = response.json()
    except ValueError:
        info = {}
    name = info.get("name") if isinstance(info, dict) else None
    return {"id": app_id, "name": str(name or KNOWN[app_id])}


def _one_per_name(answers: list[dict[str, str] | None]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for answer in answers:
        if answer is not None:
            found.setdefault(answer["name"].lower(), answer)
    return list(found.values())


def installed(host: str) -> list[dict[str, str]]:
    """The well-known apps the TV has: [{"id", "name"}], one per name, or
    [] when it answers neither way."""
    for way in WAYS:
        base = way.format(host=host)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            with ThreadPoolExecutor(max_workers=10) as pool:
                answers = list(pool.map(_ask, [base] * len(KNOWN), KNOWN))
        found = _one_per_name(answers)
        if found:
            return found
    return []


def common() -> list[dict[str, str]]:
    """The well-known apps, one per name, for a TV that will not say."""
    return _one_per_name([{"id": i, "name": n} for i, n in KNOWN.items()])

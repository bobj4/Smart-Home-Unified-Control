"""The apps on a Samsung TV that will not list them.

Many 2020+ TVs ignore the "installed apps" request (samsungtvws: "not
available on all TVs"), so the app asks instead about well-known apps one
by one: GET http://<tv>:8001/api/v2/applications/<app id> answers for an
installed app (with its name) and 404s for one that is not.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

ASK_SECONDS = 2.5
# Samsung's store ids of well-known apps (an id the TV does not have just
# answers 404). Some apps have had more than one id.
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


def _ask(host: str, app_id: str) -> dict[str, str] | None:
    try:
        response = requests.get(
            f"http://{host}:8001/api/v2/applications/{app_id}", timeout=ASK_SECONDS
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


def installed(host: str) -> list[dict[str, str]]:
    """The well-known apps the TV has: [{"id", "name"}], one per name."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(lambda app_id: _ask(host, app_id), KNOWN))
    found: dict[str, dict[str, str]] = {}
    for answer in answers:
        if answer is not None:
            found.setdefault(answer["name"].lower(), answer)
    return list(found.values())

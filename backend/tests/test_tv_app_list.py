# ruff: noqa: F811 (fixtures shared with test_samsung)
"""A TV that will not list its apps (many 2020+ models) is asked about
well-known apps one by one; a TV that is off says so (not a 502)."""

from app import tv_app_catalog, tv_power
from app.integrations import samsung
from tests.test_samsung import ready_tv, secrets_key, tv, url  # noqa: F401


class Answer:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.data = data

    def json(self):
        if self.data is None:
            raise ValueError("not JSON")
        return self.data


def fake_tv(installed):
    asked = []

    def get(address, timeout):
        asked.append(address)
        app_id = address.rsplit("/", 1)[1]
        if app_id not in installed:
            return Answer(404)
        return Answer(200, {"id": app_id, "name": installed[app_id], "running": False})

    return get, asked


def test_asking_app_by_app(monkeypatch):
    get, asked = fake_tv(
        {"3201907018807": "Netflix", "11101200001": "Netflix", "3201512006963": "Plex"}
    )
    monkeypatch.setattr(tv_app_catalog.requests, "get", get)
    found = tv_app_catalog.installed("192.168.1.50")
    assert sorted(a["name"] for a in found) == ["Netflix", "Plex"]  # one Netflix
    assert asked[0].startswith("http://192.168.1.50:8001/api/v2/applications/")
    assert len(asked) == len(tv_app_catalog.KNOWN)


def apps_url(owner, device_id):
    return url(owner.home_id, f"/integrations/samsung_tv/tvs/{device_id}/apps")


def test_a_tv_that_will_not_list_its_apps(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)

    def no_list(host, protocol, token):
        raise samsung.TvError("could not reach the TV: timed out")

    monkeypatch.setattr(samsung, "installed_apps", no_list)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: "on")
    get, _ = fake_tv({"111299001912": "YouTube", "3201807016597": "Apple TV"})
    monkeypatch.setattr(tv_app_catalog.requests, "get", get)
    r = client.get(apps_url(owner, device_id))
    assert r.status_code == 200, r.text
    assert [a["name"] for a in r.json()] == ["Apple TV", "YouTube"]
    # Nothing it knows either: the TV's own error.
    monkeypatch.setattr(tv_app_catalog.requests, "get", fake_tv({})[0])
    r = client.get(apps_url(owner, device_id))
    assert r.status_code == 502 and "timed out" in r.json()["detail"]


def test_a_tv_that_is_off(client, owner, login, csrf, tv, secrets_key, monkeypatch):
    device_id = ready_tv(client, csrf, login, owner, tv)
    monkeypatch.setattr(
        samsung,
        "installed_apps",
        lambda host, protocol, token: (_ for _ in ()).throw(samsung.TvError("x")),
    )
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    r = client.get(apps_url(owner, device_id))
    assert r.status_code == 409
    assert (
        r.json()["detail"]
        == "the TV is off or not answering: turn it on, then try again"
    )

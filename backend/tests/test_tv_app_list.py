# ruff: noqa: F811 (fixtures shared with test_samsung)
"""A TV that will not list its apps (many 2020+ models) is asked about
well-known apps one by one, on port 8001 and then 8002; one that will not
say even then offers the common apps; a TV that is off says so (not a 502)."""

from playwright.sync_api import expect

from app import tv_app_catalog, tv_power
from app.integrations import samsung
from app.routes import samsung as samsung_routes
from tests import test_ui as _ui
from tests.test_samsung import ready_tv, secrets_key, tv, url  # noqa: F401
from tests.test_tv_quick_apps import _ui_tv


class Answer:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self.data = data

    def json(self):
        if self.data is None:
            raise ValueError("not JSON")
        return self.data


def fake_tv(installed, port=8001):
    asked = []

    def get(address, timeout, verify=True):
        asked.append(address)
        app_id = address.rsplit("/", 1)[1]
        if f":{port}/" not in address or app_id not in installed:
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
    assert len(asked) == len(tv_app_catalog.KNOWN)  # found: 8002 not asked


def test_newer_tvs_answer_on_8002_only(monkeypatch):
    get, asked = fake_tv({"111299001912": "YouTube"}, port=8002)
    monkeypatch.setattr(tv_app_catalog.requests, "get", get)
    assert tv_app_catalog.installed("192.168.1.50") == [
        {"id": "111299001912", "name": "YouTube"}
    ]
    assert asked[-1].startswith("https://192.168.1.50:8002/api/v2/applications/")
    assert len(asked) == 2 * len(tv_app_catalog.KNOWN)


def test_common_apps_one_per_name():
    common = tv_app_catalog.common()
    names = [a["name"] for a in common]
    assert len(names) == len(set(names))
    by_name = {a["name"]: a["id"] for a in common}
    # The ids the remote's usual buttons use.
    assert by_name["Netflix"] == samsung.APP_IDS["netflix"]
    assert by_name["Prime Video"] == samsung.APP_IDS["prime_video"]


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
    assert not any(a.get("unconfirmed") for a in r.json())
    # It will not say which it has either way: the common apps, not a 502.
    monkeypatch.setattr(tv_app_catalog.requests, "get", fake_tv({})[0])
    r = client.get(apps_url(owner, device_id))
    assert r.status_code == 200, r.text
    names = [a["name"] for a in r.json()]
    assert "Netflix" in names and names == sorted(names, key=str.lower)
    assert all(a["unconfirmed"] is True for a in r.json())


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


def test_ui_common_apps_say_so(open_page, db, owner, make_device, monkeypatch):
    _ui_tv(db, owner, make_device)
    common = [{**a, "unconfirmed": True} for a in tv_app_catalog.common()]
    monkeypatch.setattr(samsung_routes, "tv_apps", lambda db, device: common)
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.card(page, "Den TV").get_by_test_id("tv-quick-menu").click()
    panel = page.get_by_test_id("quick-apps-panel")
    expect(panel.get_by_test_id("quick-apps-unconfirmed")).to_contain_text(
        "won't say which apps it has"
    )
    expect(panel.get_by_test_id(f"quick-app-{common[0]['id']}")).to_be_visible()
    expect(panel.get_by_test_id("quick-apps-error")).to_be_empty()


def test_the_tv_library_timing_out_is_not_a_500(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    """The TV library's own websocket timeout (not a TvError) crashed it."""
    import websocket

    device_id = ready_tv(client, csrf, login, owner, tv)

    def times_out(host, protocol, token):
        raise websocket.WebSocketTimeoutException("timed out")

    monkeypatch.setattr(samsung, "installed_apps", times_out)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: "on")
    get, _ = fake_tv({"111299001912": "YouTube"})
    monkeypatch.setattr(tv_app_catalog.requests, "get", get)
    r = client.get(apps_url(owner, device_id))
    assert r.status_code == 200, r.text
    assert r.json() == [{"id": "111299001912", "name": "YouTube"}]


def test_a_tv_that_never_answers_the_list_is_not_waited_on(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    import threading
    import time

    from app import samsung_home

    device_id = ready_tv(client, csrf, login, owner, tv)
    release = threading.Event()

    def waits(host, protocol, token):
        release.wait(10)
        return []

    monkeypatch.setattr(samsung, "installed_apps", waits)
    monkeypatch.setattr(samsung_home, "LIST_SECONDS", 0.3)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: "on")
    monkeypatch.setattr(tv_app_catalog.requests, "get", fake_tv({})[0])
    started = time.monotonic()
    r = client.get(apps_url(owner, device_id))
    release.set()
    assert r.status_code == 200, r.text
    assert time.monotonic() - started < 3
    assert r.json() and all(a["unconfirmed"] for a in r.json())  # the common ones

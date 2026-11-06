"""Quick-app buttons start the app the way the TV expects."""

from app.integrations import samsung


class FakeTv:
    def __init__(self, apps=None, rest_works=True, list_works=True):
        self.apps, self.rest_works, self.list_works = apps or [], rest_works, list_works
        self.calls = []

    def app_list(self):
        if not self.list_works:
            raise RuntimeError("not on this TV")
        return self.apps

    def run_app(self, app_id, app_type="DEEP_LINK", meta_tag=""):
        self.calls.append(("ws", app_id, app_type))

    def rest_app_run(self, app_id):
        if not self.rest_works:
            raise RuntimeError("404")
        self.calls.append(("rest", app_id))


def test_kind_from_the_tvs_own_list(monkeypatch):
    monkeypatch.setattr(samsung, "APP_SETTLE_SECONDS", 0)
    tv = FakeTv(
        apps=[
            {"appId": "111299001912", "app_type": 2, "name": "YouTube"},
            {"appId": "3201907018807", "app_type": 4, "name": "Netflix"},
        ]
    )
    samsung._start_app(tv, "111299001912")
    samsung._start_app(tv, "3201907018807")
    assert tv.calls == [
        ("ws", "111299001912", "DEEP_LINK"),
        ("ws", "3201907018807", "NATIVE_LAUNCH"),
    ]


def test_unlisted_app_uses_rest_then_websocket(monkeypatch):
    monkeypatch.setattr(samsung, "APP_SETTLE_SECONDS", 0)
    tv = FakeTv(list_works=False)
    samsung._start_app(tv, "3201907018807")
    assert tv.calls == [("rest", "3201907018807")]
    old = FakeTv(list_works=False, rest_works=False)
    samsung._start_app(old, "3201907018807")
    assert old.calls == [("ws", "3201907018807", "NATIVE_LAUNCH")]


def test_installed_apps(monkeypatch):
    tv = FakeTv(apps=[{"appId": "1", "name": "Netflix"}, {"appId": "", "name": "x"}])
    monkeypatch.setattr(samsung, "_tizen_call", lambda host, token, action: action(tv))
    assert samsung.installed_apps("10.0.0.5", "tizen", "t") == [
        {"id": "1", "name": "Netflix"}
    ]
    assert samsung.installed_apps("10.0.0.5", "legacy", None) == []

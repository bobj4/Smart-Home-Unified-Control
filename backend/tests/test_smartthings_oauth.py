# ruff: noqa: F811 (a fixture shared with test_samsung)
"""SmartThings by signing in (OAuth): it renews itself, unlike a personal
token that lasts 24 hours. Nothing here reaches SmartThings."""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from app import credentials, features, integration_status, smartthings_oauth
from app.integrations import smartthings
from tests import test_ui as _ui
from tests.test_samsung import secrets_key  # noqa: F401 (a shared fixture)

CALLBACK = "/api/v1/smartthings/callback"
REDIRECT = "https://home.example.com" + CALLBACK
APP = {"client_id": "client-1", "client_secret": "secret-2", "redirect_uri": REDIRECT}


class FakeSmartThings:
    def __init__(self):
        self.grants = []
        self.deny = False
        self.n = 0

    def token_request(self, client_id, client_secret, form):
        assert (client_id, client_secret) == ("client-1", "secret-2")
        self.grants.append(dict(form))
        if self.deny:
            raise smartthings.SmartThingsDenied("SmartThings refused the sign-in")
        self.n += 1
        return {
            "access_token": f"access-{self.n}",
            "refresh_token": f"refresh-{self.n}",
            "expires_in": 86399,
        }

    def tvs(self, token):
        assert token.startswith("access-") or token == TOKEN  # signed in, or pasted
        return [{"id": "st-tv", "name": "Den TV"}]


@pytest.fixture
def st(monkeypatch):
    fake = FakeSmartThings()
    monkeypatch.setattr(smartthings, "token_request", fake.token_request)
    monkeypatch.setattr(smartthings, "tvs", fake.tvs)
    integration_status.clear()
    return fake


def base(home_id):
    return f"/api/v1/homes/{home_id}/integrations/samsung_tv/smartthings"


def sign_in(client, csrf, owner, **changes):
    """Start the sign-in; returns the state SmartThings would send back."""
    r = client.post(
        f"{base(owner.home_id)}/oauth", json={**APP, **changes}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["authorize_url"])
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        "https://api.smartthings.com/oauth/authorize"
    )
    assert query["client_id"] == ["client-1"] and query["response_type"] == ["code"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["scope"] == ["r:devices:* x:devices:*"]
    return query["state"][0]


def saved(db, owner):
    return credentials.load(db, owner.home_id, smartthings_oauth.CREDENTIAL)


def test_sign_in_and_come_back(
    client, new_client, db, owner, login, csrf, st, secrets_key
):
    assert login(client, owner).status_code == 200
    state = sign_in(client, csrf, owner)
    # SmartThings sends the browser back: no login cookie comes with it.
    back = new_client().get(
        f"{CALLBACK}?code=abc123&state={state}", follow_redirects=False
    )
    assert back.status_code == 303
    assert back.headers["location"] == "/?smartthings=connected#settings/integrations"
    assert st.grants == [
        {"grant_type": "authorization_code", "code": "abc123", "redirect_uri": REDIRECT}
    ]
    login_saved = saved(db, owner)
    assert login_saved["oauth"] is True and login_saved["access_token"] == "access-1"
    assert login_saved["refresh_token"] == "refresh-1"
    info = client.get(base(owner.home_id)).json()
    assert info["connected"] is True and info["method"] == "oauth"
    assert info["tvs"] == [{"id": "st-tv", "name": "Den TV"}]
    # The state works once.
    again = new_client().get(
        f"{CALLBACK}?code=abc&state={state}", follow_redirects=False
    )
    assert "smartthings_error=" in again.headers["location"]


def test_coming_back_without_a_sign_in(new_client, st):
    for query in ("code=abc&state=made-up", "error=access_denied&state=x", ""):
        r = new_client().get(f"{CALLBACK}?{query}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/?smartthings_error=")
    assert st.grants == []


def test_sign_in_needs_https_the_callback_and_an_operator(
    client, owner, login, csrf, make_user, new_client, st
):
    assert login(client, owner).status_code == 200
    url = f"{base(owner.home_id)}/oauth"
    for redirect, status in (
        ("http://home.example.com" + CALLBACK, 422),
        ("https://home.example.com/elsewhere", 422),
    ):
        r = client.post(
            url, json={**APP, "redirect_uri": redirect}, headers=csrf(client)
        )
        assert r.status_code == status, redirect
    # No ID and secret, and none saved yet.
    r = client.post(url, json={"redirect_uri": REDIRECT}, headers=csrf(client))
    assert r.status_code == 422
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert other.post(url, json=APP, headers=csrf(other)).status_code == 403


def connect(db, owner, **changes):
    now = time.time()
    data = {
        "oauth": True,
        **APP,
        "access_token": "access-0",
        "refresh_token": "refresh-0",
        "expires_at": now + 86000,
        "renewed_at": now,
        "problem": None,
        **changes,
    }
    credentials.save(
        db, owner.home_id, smartthings_oauth.CREDENTIAL, "SmartThings", data
    )


def test_renews_every_twelve_hours(db, owner, st, secrets_key):
    connect(db, owner)
    assert smartthings_oauth.keep_fresh(db, owner.home_id) is False  # still new
    connect(db, owner, renewed_at=time.time() - 13 * 3600)
    assert smartthings_oauth.keep_fresh(db, owner.home_id) is True
    assert st.grants == [{"grant_type": "refresh_token", "refresh_token": "refresh-0"}]
    # Each refresh token works once: the new one is kept.
    assert saved(db, owner)["refresh_token"] == "refresh-1"
    assert saved(db, owner)["access_token"] == "access-1"


def test_a_token_about_to_end_is_renewed_before_use(db, owner, st, secrets_key):
    connect(db, owner, expires_at=time.time() + 60)
    token = smartthings_oauth.access_token(db, owner.home_id, saved(db, owner))
    assert token == "access-1" and len(st.grants) == 1
    # A saved personal token is used as it is.
    assert smartthings_oauth.access_token(db, owner.home_id, {"token": "pat"}) == "pat"


def test_a_lapsed_sign_in_asks_to_connect_again(
    client, db, owner, login, st, secrets_key
):
    connect(db, owner, renewed_at=time.time() - 13 * 3600)
    st.deny = True
    assert smartthings_oauth.keep_fresh(db, owner.home_id) is False
    assert saved(db, owner)["problem"] == smartthings_oauth.RECONNECT
    assert integration_status.for_home(owner.home_id)["samsung_tv"]["reason"] == (
        smartthings_oauth.RECONNECT
    )
    assert smartthings_oauth.keep_fresh(db, owner.home_id) is False  # not again
    assert len(st.grants) == 1
    assert login(client, owner).status_code == 200
    info = client.get(base(owner.home_id)).json()
    assert info["connected"] is True and info["problem"] == smartthings_oauth.RECONNECT


def test_sign_in_again_with_the_saved_app(
    client, new_client, db, owner, login, csrf, st, secrets_key
):
    connect(db, owner, problem=smartthings_oauth.RECONNECT)
    assert login(client, owner).status_code == 200
    state = sign_in(client, csrf, owner, client_id="", client_secret="")
    new_client().get(f"{CALLBACK}?code=c2&state={state}", follow_redirects=False)
    assert saved(db, owner)["problem"] is None
    assert saved(db, owner)["access_token"] == "access-1"


def test_ui_sign_in_form_and_the_way_back(open_page, db, owner, st, secrets_key):
    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    page = open_page()
    _ui.ui_login(page, owner)
    page.goto(page.url.split("#")[0] + "#/settings/integrations")
    panel = page.get_by_test_id("smartthings")
    expect(panel.get_by_test_id("smartthings-setup-connect")).to_be_visible()
    expect(panel.get_by_test_id("smartthings-token")).to_be_visible()  # still offered
    expect(panel).not_to_contain_text("null")
    # One's own SmartApp: folded away, and plainly not the Samsung login.
    expect(panel.get_by_test_id("smartthings-signin")).not_to_be_visible()
    panel.get_by_test_id("smartthings-own-app").locator("summary").click()
    expect(panel.get_by_test_id("smartthings-redirect")).to_have_text(
        page.url.split("/#")[0].rstrip("/") + CALLBACK
    )
    expect(panel.get_by_test_id("smartthings-own-app")).to_contain_text(
        "not your Samsung password"
    )
    # Back from SmartThings: says so, and tidies the address.
    connect(db, owner)
    page.goto(
        page.url.split("#")[0].split("?")[0]
        + "?smartthings=connected#/settings/integrations"
    )
    expect(page.get_by_test_id("status")).to_contain_text("SmartThings connected")
    expect(panel.get_by_test_id("smartthings-method")).to_contain_text("renews itself")
    assert "smartthings=" not in page.url


TOKEN = "0123456789abcdef-0123456789abcdef"


class Answer:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data

    def json(self):
        return self.data


def test_register_app_asks_like_the_cli(monkeypatch):
    asked = {}

    def post(url, headers, json, timeout):
        asked.update(url=url, headers=headers, json=json)
        return Answer(
            200,
            {
                "app": {"appId": "app-1"},
                "oauthClientId": "client-1",
                "oauthClientSecret": "secret-2",
            },
        )

    monkeypatch.setattr(smartthings.requests, "post", post)
    made = smartthings.register_app(TOKEN, REDIRECT, "abcd")
    assert made == {
        "app_id": "app-1",
        "client_id": "client-1",
        "client_secret": "secret-2",
    }
    assert asked["url"] == "https://api.smartthings.com/v1/apps"
    assert asked["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    body = asked["json"]
    assert (body["appType"], body["classifications"]) == (
        "API_ONLY",
        ["CONNECTED_SERVICE"],
    )
    assert body["appName"] == "smart-home-unified-control-abcd"
    assert body["oauth"]["scope"] == ["r:devices:*", "x:devices:*"]
    assert body["oauth"]["redirectUris"] == [REDIRECT]
    monkeypatch.setattr(smartthings.requests, "post", lambda *a, **k: Answer(403, {}))
    with pytest.raises(smartthings.SmartThingsDenied, match="Apps"):
        smartthings.register_app(TOKEN, REDIRECT, "abcd")
    refused = {"error": {"message": "x", "details": [{"message": "appName taken"}]}}
    monkeypatch.setattr(
        smartthings.requests, "post", lambda *a, **k: Answer(422, refused)
    )
    with pytest.raises(smartthings.SmartThingsError, match="appName taken"):
        smartthings.register_app(TOKEN, REDIRECT, "abcd")


def test_one_token_setup(
    client, new_client, db, owner, login, csrf, st, monkeypatch, secrets_key
):
    registered = []

    def register(token, redirect_uri, suffix):
        registered.append((token, redirect_uri))
        return {"app_id": "app-1", "client_id": "client-1", "client_secret": "secret-2"}

    monkeypatch.setattr(smartthings, "register_app", register)
    assert login(client, owner).status_code == 200
    url = f"{base(owner.home_id)}/setup"
    r = client.post(
        url, json={"token": TOKEN, "redirect_uri": REDIRECT}, headers=csrf(client)
    )
    assert r.status_code == 200, r.text
    assert r.json()["problem"] is None
    assert r.json()["authorize_url"].startswith(
        "https://api.smartthings.com/oauth/authorize?"
    )
    assert registered == [(TOKEN, REDIRECT)]
    # Connected with the token straight away (for its 24 hours).
    assert saved(db, owner) == {"token": TOKEN}
    info = client.get(base(owner.home_id)).json()
    assert info["method"] == "token" and info["app_registered"] is True
    # Coming back from Samsung: signed in for good.
    state = parse_qs(urlparse(r.json()["authorize_url"]).query)["state"][0]
    new_client().get(f"{CALLBACK}?code=c1&state={state}", follow_redirects=False)
    assert saved(db, owner)["oauth"] is True
    # Again (a new token): the registered app is used, not registered again.
    r = client.post(
        url, json={"token": TOKEN, "redirect_uri": REDIRECT}, headers=csrf(client)
    )
    assert len(registered) == 1 and r.json()["authorize_url"]
    assert saved(db, owner)["oauth"] is True  # a working sign-in is kept


def test_setup_without_the_apps_permission(
    client, db, owner, login, csrf, st, monkeypatch, secrets_key
):
    def register(token, redirect_uri, suffix):
        raise smartthings.SmartThingsDenied(
            'the token cannot register an app: tick "Apps"'
        )

    monkeypatch.setattr(smartthings, "register_app", register)
    assert login(client, owner).status_code == 200
    url = f"{base(owner.home_id)}/setup"
    r = client.post(
        url, json={"token": TOKEN, "redirect_uri": REDIRECT}, headers=csrf(client)
    )
    assert r.json() == {
        "authorize_url": None,
        "problem": 'the token cannot register an app: tick "Apps"',
    }
    assert saved(db, owner) == {"token": TOKEN}  # still connected for now
    monkeypatch.setattr(
        smartthings,
        "tvs",
        lambda token: (_ for _ in ()).throw(smartthings.SmartThingsDenied("no")),
    )
    r = client.post(
        url, json={"token": TOKEN, "redirect_uri": REDIRECT}, headers=csrf(client)
    )
    assert r.status_code == 422 and "Devices permissions" in r.json()["detail"]


def test_what_smartthings_sent_back_is_said(new_client):
    def back(query):
        r = new_client().get(f"{CALLBACK}?{query}", follow_redirects=False)
        return parse_qs(urlparse(r.headers["location"]).query)["smartthings_error"][0]

    assert "known SmartThings fault" in back("error=unsupported_response_type&state=x")
    assert "declined" in back("error=access_denied")
    assert "(Bad thing)" in back("error=server_error&error_description=Bad+thing")
    assert "it sent: nothing" in back("")
    assert "it sent: state" in back("state=abc")

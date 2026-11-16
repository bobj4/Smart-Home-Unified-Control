"""SmartThings limits how often it is asked (HTTP 429): the account's TV list
is reused for a minute (Settings redraws every few seconds), and a 429 says
to wait instead of "SmartThings answered 429"."""

import pytest

from app import credentials, smartthings_oauth, tv_sources
from app.integrations import smartthings
from tests import test_smartthings_oauth
from tests.test_smartthings_oauth import TOKEN, base

secrets_key = test_smartthings_oauth.secrets_key  # its fixture


class Answer:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = b""


@pytest.mark.parametrize(
    ("headers", "wait"),
    [
        ({"Retry-After": "300"}, "about 5 minutes"),
        ({"Retry-After": "20"}, "about 1 minute"),
        ({}, "a few minutes"),
    ],
)
def test_a_429_says_how_long_to_wait(monkeypatch, headers, wait):
    monkeypatch.setattr(
        smartthings.requests, "request", lambda *a, **k: Answer(429, headers)
    )
    with pytest.raises(smartthings.SmartThingsBusy) as caught:
        smartthings.tvs(TOKEN)
    assert str(caught.value) == (
        f"SmartThings is limiting requests for now (too many): try again in {wait}"
    )


def test_the_tv_list_is_reused_for_a_minute(
    client, db, owner, login, monkeypatch, secrets_key
):  # noqa: F811
    from app import features

    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    credentials.save(
        db, owner.home_id, smartthings_oauth.CREDENTIAL, "SmartThings", {"token": TOKEN}
    )
    asked = []

    def tvs(token):
        asked.append(token)
        return [{"id": "st-1", "name": "Den TV"}]

    monkeypatch.setattr(smartthings, "tvs", tvs)
    monkeypatch.setattr(tv_sources, "_listed", {})
    clock = [1000.0]
    monkeypatch.setattr(tv_sources.time, "monotonic", lambda: clock[0])
    assert login(client, owner).status_code == 200
    for _ in range(5):  # the page redrawing every few seconds
        assert client.get(base(owner.home_id)).json()["tvs"][0]["name"] == "Den TV"
        clock[0] += 5
    assert len(asked) == 1
    clock[0] += tv_sources.LIST_SECONDS
    client.get(base(owner.home_id))
    assert len(asked) == 2  # a minute on: asked again
    credentials.save(
        db,
        owner.home_id,
        smartthings_oauth.CREDENTIAL,
        "SmartThings",
        {"token": "t" * 20},
    )
    client.get(base(owner.home_id))
    assert asked[-1] == "t" * 20  # a new token: asked at once
    tv_sources.disconnect(db, owner.home_id)
    assert owner.home_id not in tv_sources._listed


def test_busy_shows_on_the_panel(client, db, owner, login, monkeypatch, secrets_key):  # noqa: F811
    from app import features

    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    credentials.save(
        db, owner.home_id, smartthings_oauth.CREDENTIAL, "SmartThings", {"token": TOKEN}
    )
    monkeypatch.setattr(tv_sources, "_listed", {})

    def busy(token):
        raise smartthings.SmartThingsBusy(
            "SmartThings is limiting requests for now (too many): try again in a few minutes"
        )

    monkeypatch.setattr(smartthings, "tvs", busy)
    assert login(client, owner).status_code == 200
    info = client.get(base(owner.home_id)).json()
    assert info["connected"] is True and "try again in a few minutes" in info["problem"]
    saved = credentials.load(db, owner.home_id, smartthings_oauth.CREDENTIAL)
    assert "problem" not in saved  # not kept: it passes

# ruff: noqa: F811 (fixtures shared with test_samsung)
"""An older TV often goes off before it answers the power key: turning it
off is not an error when it no longer answers afterwards."""

from app import tv_power
from app.integrations import samsung
from tests.test_samsung import command, ready_tv, secrets_key, tv  # noqa: F401

GONE = "could not reach the TV: it did not answer (off, asleep, or not on this network)"


def test_off_before_answering_is_off(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    answers = {"on": False}
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: answers["on"])
    tv.fail = samsung.TvError(GONE)
    r = command(client, csrf, owner.home_id, device_id, "turn_off")
    assert r.status_code == 200, r.text
    # Still answering: the key really did not get through.
    answers["on"] = True
    tv.fail = samsung.TvError(GONE)
    r = command(client, csrf, owner.home_id, device_id, "turn_off")
    assert r.status_code == 502 and r.json()["detail"] == GONE


def test_turning_on_still_reports_it(
    client, owner, login, csrf, tv, secrets_key, monkeypatch
):
    device_id = ready_tv(client, csrf, login, owner, tv)
    monkeypatch.setattr(tv_power, "power_state", lambda host, protocol: None)
    monkeypatch.setattr(samsung, "is_on", lambda host, protocol: False)
    tv.fail = samsung.TvError(GONE)
    r = command(client, csrf, owner.home_id, device_id, "turn_on")
    assert r.status_code == 502

# ruff: noqa: F811 (fixtures shared with test_thermostat and test_thermostat_settings)
"""Guests and their thermostats' Settings: two ticks in the guest's Access
window, checked by the guest routes on every request."""

from playwright.sync_api import expect

from tests import test_guest as _guest
from tests import test_thermostat as _thermostat
from tests import test_thermostat_settings as _settings
from tests import test_ui as _ui

fake, secrets_key, thermostat = (
    _thermostat.fake,
    _thermostat.secrets_key,
    _thermostat.thermostat,
)
held = _settings.held


def grant(client, csrf, owner, guest, **changes):
    """The owner (logged in on client) sets the guest's access."""
    url = f"/api/v1/homes/{owner.home_id}/members/{guest.id}/guest-access"
    r = client.put(url, json={**_guest.NONE, **changes}, headers=csrf(client))
    assert r.status_code == 200, r.text
    return r.json()


def guest_url(owner, thermostat):
    return f"/api/v1/homes/{owner.home_id}/guest/devices/{thermostat.id}/settings"


def test_guest_settings_follow_their_access(
    client, new_client, owner, make_user, login, csrf, thermostat, held
):
    guest = make_user(owner.home_id, role="guest")
    url = guest_url(owner, thermostat)
    g = new_client()
    assert login(g, guest).status_code == 200
    # Their thermostat, but no Settings tick: refused.
    grant(client, csrf, owner, guest, thermostat_ids=[thermostat.id])
    assert g.get(url).status_code == 403
    # Settings, not installer settings.
    access = grant(
        client,
        csrf,
        owner,
        guest,
        thermostat_ids=[thermostat.id],
        thermostat_settings=True,
    )
    assert (
        access["thermostat_settings"] is True
        and access["thermostat_installer"] is False
    )
    r = g.get(url)
    assert r.status_code == 200 and r.json()["installer_allowed"] is False
    assert g.put(url, json={"early_on": True}, headers=csrf(g)).status_code == 200
    assert g.put(url, json={"furnace_type": 1}, headers=csrf(g)).status_code == 403
    # And installer settings.
    grant(
        client,
        csrf,
        owner,
        guest,
        thermostat_ids=[thermostat.id],
        thermostat_settings=True,
        thermostat_installer=True,
    )
    assert g.get(url).json()["installer_allowed"] is True
    assert g.put(url, json={"furnace_type": 1}, headers=csrf(g)).status_code == 200
    # Not their thermostat: not found. The member route: refused.
    grant(client, csrf, owner, guest, thermostat_settings=True)
    assert g.get(url).status_code == 404
    assert g.get(_settings.url(owner, thermostat)).status_code == 403


def test_ui_access_window_has_the_ticks(open_page, owner, make_user):
    guest = make_user(owner.home_id, role="guest")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "members")
    row = page.get_by_test_id("member-row").filter(has_text=guest.email)
    row.get_by_test_id("guest-access-open").click()
    dialog = page.get_by_test_id("guest-access")
    expect(dialog.get_by_test_id("guest-thermostat_settings")).not_to_be_checked()
    expect(dialog.get_by_test_id("guest-thermostat_installer")).not_to_be_checked()


def test_ui_guest_sees_settings_only_when_allowed(
    open_page, client, owner, make_user, csrf, thermostat
):
    guest = make_user(owner.home_id, role="guest")
    grant(client, csrf, owner, guest, thermostat_ids=[thermostat.id])
    page = open_page()
    _ui.ui_login(page, guest)
    tile = _ui.card(page, "Hallway")
    expect(tile.get_by_test_id("thermo-hold")).to_be_visible()
    expect(tile.get_by_test_id("thermo-settings-open")).to_have_count(0)
    expect(tile.get_by_test_id("thermo-schedule-open")).to_have_count(0)
    grant(
        client,
        csrf,
        owner,
        guest,
        thermostat_ids=[thermostat.id],
        thermostat_settings=True,
    )
    page.reload()
    expect(
        _ui.card(page, "Hallway").get_by_test_id("thermo-settings-open")
    ).to_be_visible()

# ruff: noqa: F811 (fixtures shared with test_thermostat and test_thermostat_settings)
"""Settings > Safety Settings: who may change thermostat installer settings."""

from playwright.sync_api import expect

from app.models import AuditEvent
from tests import test_thermostat as _thermostat
from tests import test_thermostat_settings as _settings
from tests import test_ui as _ui

fake, secrets_key, thermostat = (
    _thermostat.fake,
    _thermostat.secrets_key,
    _thermostat.thermostat,
)
held = _settings.held


def access_url(owner):
    return f"/api/v1/homes/{owner.home_id}/thermostat-access"


def test_access_follows_the_home_setting(
    client, db, owner, csrf, thermostat, held, make_user, new_client, login
):
    assert client.get(access_url(owner)).json() == {
        "installer_role": "admin",
        "you_may": True,
    }
    operator = make_user(owner.home_id, role="operator")
    o = new_client()
    assert login(o, operator).status_code == 200
    settings = _settings.url(owner, thermostat)
    assert o.get(settings).json()["installer_allowed"] is False
    assert o.put(settings, json={"furnace_type": 1}, headers=csrf(o)).status_code == 403
    # Only admins choose who may.
    assert (
        o.put(
            access_url(owner), json={"installer_role": "operator"}, headers=csrf(o)
        ).status_code
        == 403
    )
    r = client.put(
        access_url(owner), json={"installer_role": "operator"}, headers=csrf(client)
    )
    assert r.status_code == 200 and r.json()["installer_role"] == "operator"
    assert o.get(settings).json()["installer_allowed"] is True
    assert o.put(settings, json={"furnace_type": 1}, headers=csrf(o)).status_code == 200
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert m.put(settings, json={"furnace_type": 0}, headers=csrf(m)).status_code == 403
    assert m.put(settings, json={"early_on": True}, headers=csrf(m)).status_code == 200
    bad = client.put(
        access_url(owner), json={"installer_role": "guest"}, headers=csrf(client)
    )
    assert bad.status_code == 422
    db.expire_all()
    assert (
        db.query(AuditEvent).filter_by(event_type="thermostat_access_changed").count()
        == 1
    )


def test_ui_safety_settings_page(open_page, owner, make_device, make_user):
    make_device(owner.home_id, device_type="thermostat", name="Hallway")
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "safety")
    expect(page.get_by_test_id("settings-nav-safety")).to_have_text("Safety Settings")
    choice = page.get_by_test_id("thermostat-installer-role")
    expect(choice).to_have_value("admin")
    choice.select_option("operator")
    expect(page.get_by_test_id("status")).to_contain_text("operators and admins")
    page.reload()
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    expect(page.get_by_test_id("thermostat-installer-role")).to_have_value("operator")

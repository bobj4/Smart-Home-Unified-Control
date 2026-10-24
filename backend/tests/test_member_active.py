"""Turning a member's account off (inactive) and on again. Written by the
reviewer. Do not edit, skip, mark or delete these tests."""

import time

from playwright.sync_api import expect

from app.models import AuditEvent, User
from app.models import Session as SessionModel
from tests import test_ui as _ui

go_settings, ui_login, member_row = _ui.go_settings, _ui.ui_login, _ui.member_row


def url(home_id, user_id):
    return f"/api/v1/homes/{home_id}/members/{user_id}/active"


def test_inactive_member_is_logged_out_and_cannot_log_in(
    client, new_client, db, owner, make_user, login, csrf
):
    member = make_user(owner.home_id, role="member")
    theirs = new_client()
    earlier = member.totp.at(time.time() - 30)  # leave later codes unused
    assert login(theirs, member, earlier).status_code == 200
    assert theirs.get("/api/v1/account").status_code == 200

    assert login(client, owner).status_code == 200
    rows = client.get(f"/api/v1/homes/{owner.home_id}/members/status").json()
    assert rows[member.id] is True
    r = client.put(
        url(owner.home_id, member.id), json={"active": False}, headers=csrf(client)
    )
    assert r.status_code == 200 and r.json() == {"user_id": member.id, "active": False}
    db.expire_all()
    assert db.get(User, member.id).is_active is False
    assert db.query(SessionModel).filter_by(user_id=member.id).count() == 0
    assert theirs.get("/api/v1/account").status_code == 401  # logged out at once
    assert login(new_client(), member).status_code == 401  # and cannot log in
    rows = client.get(f"/api/v1/homes/{owner.home_id}/members/status").json()
    assert rows[member.id] is False

    r = client.put(
        url(owner.home_id, member.id), json={"active": True}, headers=csrf(client)
    )
    assert r.status_code == 200
    later = member.totp.at(time.time() + 30)
    assert login(new_client(), member, later).status_code == 200
    db.expire_all()
    kinds = [e.event_type for e in db.query(AuditEvent).order_by(AuditEvent.id)]
    assert "member_deactivated" in kinds and "member_activated" in kinds


def test_only_admins_and_never_yourself(
    client, new_client, owner, make_user, login, csrf
):
    member = make_user(owner.home_id, role="member")
    operator = make_user(owner.home_id, role="operator")
    assert login(client, owner).status_code == 200
    r = client.put(
        url(owner.home_id, owner.id), json={"active": False}, headers=csrf(client)
    )
    assert r.status_code == 409
    r = client.put(
        url(owner.home_id, "nobody"), json={"active": False}, headers=csrf(client)
    )
    assert r.status_code == 404
    r = client.put(
        url(owner.home_id, member.id), json={"active": "no"}, headers=csrf(client)
    )
    assert r.status_code == 422
    theirs = new_client()
    assert login(theirs, operator).status_code == 200
    r = theirs.put(
        url(owner.home_id, member.id), json={"active": False}, headers=csrf(theirs)
    )
    assert r.status_code == 403
    r = client.put(url(owner.home_id, member.id), json={"active": False})  # no CSRF
    assert r.status_code == 403


def test_ui_active_toggle(open_page, db, owner, make_user):
    member = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "members")
    row = member_row(section, member.id)
    expect(row.get_by_test_id("member-active")).to_have_text("Active")
    expect(member_row(section, owner.id).get_by_test_id("member-active")).to_have_count(
        0
    )
    row.get_by_test_id("member-active").click()
    expect(member_row(section, member.id)).to_have_attribute("data-active", "false")
    expect(member_row(section, member.id).get_by_test_id("member-active")).to_have_text(
        "Inactive"
    )
    db.expire_all()
    assert db.get(User, member.id).is_active is False
    member_row(section, member.id).get_by_test_id("member-active").click()
    expect(member_row(section, member.id)).to_have_attribute("data-active", "true")


def test_only_admins_see_who_is_active(client, owner, make_user, login):
    member = make_user(owner.home_id, role="member")
    assert login(client, member).status_code == 200
    r = client.get(f"/api/v1/homes/{owner.home_id}/members/status")
    assert r.status_code == 403

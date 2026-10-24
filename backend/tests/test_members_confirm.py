"""Removing a member asks first, and the question stays open when the list
is redrawn (it made test_ui_members_owner_manages_roles fail on slow
machines). Written by the reviewer. Do not edit, skip, mark or delete these
tests."""

from playwright.sync_api import expect

from app.models import HomeMembership
from tests import test_ui as _ui

go_settings, ui_login, member_row = _ui.go_settings, _ui.ui_login, _ui.member_row


def test_ui_remove_question_survives_a_redraw(open_page, db, owner, make_user):
    first = make_user(owner.home_id, role="member")
    second = make_user(owner.home_id, role="member")
    page = open_page()
    ui_login(page, owner)
    section = go_settings(page, "members")
    expect(section.get_by_test_id("member-row")).to_have_count(3)
    member_row(section, first.id).get_by_test_id("member-remove").click()
    expect(
        member_row(section, first.id).get_by_test_id("member-remove-confirm")
    ).to_be_visible()

    # Changing someone else's role redraws the whole list.
    member_row(section, second.id).get_by_test_id("member-role").select_option(
        "operator"
    )
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(
        member_row(section, first.id).get_by_test_id("member-remove-confirm")
    ).to_be_visible()

    member_row(section, first.id).get_by_test_id("member-remove-cancel").click()
    expect(member_row(section, first.id).get_by_test_id("member-role")).to_be_visible()
    member_row(section, second.id).get_by_test_id("member-role").select_option("member")
    expect(page.get_by_test_id("status")).to_have_attribute("data-kind", "success")
    expect(
        member_row(section, first.id).get_by_test_id("member-remove-confirm")
    ).to_have_count(0)

    member_row(section, first.id).get_by_test_id("member-remove").click()
    member_row(section, first.id).get_by_test_id("member-remove-confirm").click()
    expect(member_row(section, first.id)).to_have_count(0)
    db.expire_all()
    assert db.query(HomeMembership).filter_by(user_id=first.id).count() == 0

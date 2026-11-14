# ruff: noqa: F811 (fixtures shared with test_package1)
"""Enrollment and reset codes an admin makes stay visible on their cards
while active (not only when made), and are emailed to the person with a
link that fills the code in, when an email server is set up."""

import re

from playwright.sync_api import expect

from app import mailer
from app.models import Enrollment, PasswordReset
from tests import test_ui as _ui
from tests.test_admin import recover, reset_code, set_policy
from tests.test_package1 import SERVER, outbox, secrets_key  # noqa: F401

CODE = re.compile(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){3}")


def members(home_id, path=""):
    return f"/api/v1/homes/{home_id}/members{path}"


def invite(client, csrf, home_id, email="new@example.com"):
    r = client.post(
        members(home_id, "/enrollments"),
        json={"email": email, "role": "member"},
        headers=csrf(client),
    )
    assert r.status_code == 201, r.text
    return r.json()


def email_server(client, csrf):
    r = client.put("/api/v1/admin/email", json=SERVER, headers=csrf(client))
    assert r.status_code == 200, r.text


def test_enrollment_code_shows_while_active(
    client, new_client, db, owner, make_user, login, csrf, secrets_key
):
    assert login(client, owner).status_code == 200
    made = invite(client, csrf, owner.home_id)
    codes = client.get(members(owner.home_id, "/codes")).json()
    assert codes["enrollments"] == {made["id"]: made["enrollment_code"]}
    assert made["emailed"] is None  # no email server
    row = db.get(Enrollment, made["id"])
    assert made["enrollment_code"] not in (row.code_secret or "")  # encrypted
    # The list still never shows it.
    listed = client.get(members(owner.home_id, "/enrollments"))
    assert made["enrollment_code"] not in listed.text
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert other.get(members(owner.home_id, "/codes")).status_code == 403


def test_without_secrets_key_it_shows_only_once(
    client, owner, login, csrf, monkeypatch
):
    monkeypatch.delenv("SECRETS_KEY", raising=False)  # even if this PC has one
    assert login(client, owner).status_code == 200
    made = invite(client, csrf, owner.home_id)
    assert CODE.fullmatch(made["enrollment_code"])
    assert client.get(members(owner.home_id, "/codes")).json()["enrollments"] == {}


def test_enrollment_code_emailed_with_a_link(
    client, new_client, db, owner, login, csrf, secrets_key, outbox
):
    assert login(client, owner).status_code == 200
    email_server(client, csrf)
    made = invite(client, csrf, owner.home_id, "Newbie@Example.com")
    assert made["emailed"] == "newbie@example.com"
    to, subject, text = outbox[-1]
    code = made["enrollment_code"]
    assert to == "newbie@example.com" and "Home A" in subject
    assert code in text and f"https://testserver/#/enroll/{code}" in text
    # Once used it is no longer kept or shown.
    guest = new_client()
    assert guest.post("/api/v1/enroll/start", json={"code": code}).status_code == 200
    db.expire_all()
    enrollment = db.get(Enrollment, made["id"])
    enrollment.used_at = enrollment.created_at
    enrollment.code_secret = None
    db.commit()
    assert client.get(members(owner.home_id, "/codes")).json()["enrollments"] == {}


def test_a_refusing_mail_server_still_gives_the_code(
    client, owner, login, csrf, secrets_key, monkeypatch
):
    assert login(client, owner).status_code == 200
    email_server(client, csrf)

    def refuse(row, to, subject, body):
        raise mailer.MailError("the email server did not accept it: SMTPAuthError")

    monkeypatch.setattr(mailer, "send", refuse)
    made = invite(client, csrf, owner.home_id)
    assert made["emailed"] is None and CODE.fullmatch(made["enrollment_code"])


def test_reset_code_shows_on_the_member_and_is_emailed(
    client, new_client, db, owner, make_user, login, csrf, secrets_key, outbox
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    email_server(client, csrf)
    made = reset_code(client, csrf, owner.home_id, member.id).json()
    assert made["emailed"] == member.email
    to, _subject, text = outbox[-1]
    code = made["reset_code"]
    assert to == member.email
    assert f"https://testserver/#/recover/{code}/{member.email}" in text
    shown = client.get(members(owner.home_id, "/codes")).json()["resets"]
    assert shown[member.id]["code"] == code
    # A newer one replaces it on the card.
    newer = reset_code(client, csrf, owner.home_id, member.id).json()["reset_code"]
    shown = client.get(members(owner.home_id, "/codes")).json()["resets"]
    assert shown[member.id]["code"] == newer
    assert recover(new_client(), member.email, newer).status_code == 200
    db.expire_all()
    assert all(
        r.code_secret is None or r.used_at is None
        for r in db.query(PasswordReset).filter_by(user_id=member.id)
    )
    shown = client.get(members(owner.home_id, "/codes")).json()["resets"]
    assert shown.get(member.id, {}).get("code") != newer  # used: gone


def test_a_code_people_email_themselves_is_not_shown(
    client, new_client, owner, make_user, login, csrf, secrets_key, outbox
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    email_server(client, csrf)
    new_client().post("/api/v1/recover/email", json={"login": member.email})
    assert client.get(members(owner.home_id, "/codes")).json()["resets"] == {}


def test_ui_codes_stay_on_the_cards(
    open_page, client, owner, make_user, login, csrf, secrets_key
):
    member = make_user(owner.home_id, role="member")
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    page = open_page()
    _ui.ui_login(page, owner, owner.totp.at(__import__("time").time() + 30))
    section = _ui.go_settings(page, "members")
    section.get_by_test_id("invite-email").fill("guest@example.com")
    section.get_by_test_id("invite-submit").click()
    code = section.get_by_test_id("invite-code").text_content()
    expect(section.get_by_test_id("invite-note")).to_contain_text("Waiting to join")
    row = section.get_by_test_id("member-row").filter(has_text=member.email)
    row.get_by_test_id("member-reset").click()
    expect(row.get_by_test_id("member-reset-code")).to_have_text(CODE)
    reset = row.get_by_test_id("member-reset-code").text_content()
    # Come back later: both still show.
    page.reload()
    section = _ui.go_settings(page, "members")
    pending = section.get_by_test_id("enrollment-row")
    expect(pending.get_by_test_id("enrollment-code")).to_have_text(code)
    row = section.get_by_test_id("member-row").filter(has_text=member.email)
    expect(row.get_by_test_id("member-reset-code")).to_have_text(reset)
    expect(row.get_by_test_id("member-reset")).to_have_text("New reset code")


def test_ui_emailed_links_fill_the_code_in(open_page, client, owner, login, csrf):
    assert login(client, owner).status_code == 200
    assert set_policy(client, csrf, allow_recovery=True).status_code == 200
    page = open_page()
    page.goto("/#/enroll/ABCD-EFGH-JKLM-NPQR")
    expect(page.get_by_test_id("enroll-code")).to_have_value("ABCD-EFGH-JKLM-NPQR")
    assert page.evaluate("location.hash") == "#/enroll"  # dropped from history
    page.goto("/#/recover/WXYZ-2345-6789-ABCD/kid%2Bhome@example.com")
    expect(page.get_by_test_id("recover-code")).to_have_value("WXYZ-2345-6789-ABCD")
    expect(page.get_by_test_id("recover-login")).to_have_value("kid+home@example.com")
    assert page.evaluate("location.hash") == "#/recover"

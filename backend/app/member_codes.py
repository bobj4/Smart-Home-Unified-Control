"""Enrollment and password-reset codes an admin makes for someone: kept
(encrypted, beside the hash that checks them) so the admin can see an
active one again on its card, and emailed to the person with a link that
opens the app with the code filled in, when an email server is set up.

The copy is dropped once the code is used. Without SECRETS_KEY nothing is
kept and the code shows only when made, as before.
"""

import logging
from urllib.parse import quote

from fastapi import Request
from sqlalchemy.orm import Session

from app import mailer, vault
from app.login_policy import settings

log = logging.getLogger(__name__)
LIFETIME_WORDS = "It works once, for 24 hours."


def keep(code: str) -> str | None:
    """The code encrypted for showing again, or None without SECRETS_KEY."""
    try:
        return vault.encrypt({"code": code})
    except vault.VaultError:
        return None


def shown(kept: str | None) -> str | None:
    if not kept:
        return None
    try:
        return str(vault.decrypt(kept)["code"])
    except (vault.VaultError, KeyError):
        return None


def link(request: Request, *parts: str) -> str:
    """This app's address as the admin reached it, at #/<parts> (after the
    #, so the code never reaches a server log)."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/#/" + "/".join(quote(part, safe="@") for part in parts)


def send(db: Session, to: str, subject: str, body: str) -> str | None:
    """Email it if an email server is set up and `to` is an email address.
    Returns where it went, or None (not set up, not an address, or the
    server refused: the admin still has the code to pass on)."""
    if "@" not in to or not mailer.configured(settings(db)):
        return None
    try:
        mailer.send_for(db, to, subject, body)
    except (mailer.MailError, vault.VaultError) as error:
        log.warning("could not email a code to %s: %s", to, error)
        return None
    return to


def enrollment_email(home: str, role: str, code: str, url: str) -> tuple[str, str]:
    return (
        f"Smart home: you're invited to {home}",
        f"You've been invited to join {home} as {role}.\n\n"
        f"Open this link to set up your account:\n{url}\n\n"
        'Or open the app, choose "Have an enrollment code?" and enter:\n'
        f"{code}\n\n{LIFETIME_WORDS}",
    )


def reset_email(home: str, code: str, url: str) -> tuple[str, str]:
    return (
        "Smart home: a code to set a new password",
        f"An admin of {home} made you a code to set a new password.\n\n"
        f"Open this link to set it:\n{url}\n\n"
        'Or open the app, choose "Forgot your password?" and enter:\n'
        f"{code}\n\n{LIFETIME_WORDS} Using it turns off two-factor login;"
        " set up your authenticator again after you log in.",
    )

"""Sending email through the server set in Settings > Admin (optional).
`send` is the only network call; tests replace it."""

import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app import vault
from app.login_policy import settings
from app.models import SystemSettings

TIMEOUT_SECONDS = 15


class MailError(Exception):
    """The email server could not be reached or refused the message."""


def configured(row: SystemSettings) -> bool:
    return bool(row.smtp_host and row.smtp_from)


def send(row: SystemSettings, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = row.smtp_from or ""
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    password = (
        str(vault.decrypt(row.smtp_password)["password"]) if row.smtp_password else None
    )
    context = ssl.create_default_context()
    try:
        if row.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                row.smtp_host or "",
                row.smtp_port,
                timeout=TIMEOUT_SECONDS,
                context=context,
            )
        else:
            server = smtplib.SMTP(
                row.smtp_host or "", row.smtp_port, timeout=TIMEOUT_SECONDS
            )
        with server:
            if row.smtp_security == "starttls":
                server.starttls(context=context)
            if row.smtp_username:
                server.login(row.smtp_username, password or "")
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(
            f"the email server did not accept it: {type(error).__name__}"
        ) from None


def send_for(db: Session, to: str, subject: str, body: str) -> None:
    row = settings(db)
    if not configured(row):
        raise MailError("no email server is set up")
    send(row, to, subject, body)

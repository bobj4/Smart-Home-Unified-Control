"""Login and logout (SEC-02 to SEC-07, B5, B7, H4, M7)."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from app.audit import record_event
from app.auth import authenticate_user, verify_recovery_code, verify_totp_code
from app.db_config import get_db
from app.dependencies import client_ip, current_session, require_csrf
from app.login_policy import settings
from app.login_times import (
    DEVICE_COOKIE,
    DEVICE_PATH,
    device_cookie_seconds,
    keep_seconds,
    remember,
    remember_me_seconds,
    trusted,
)
from app.models import Session as SessionModel
from app.models import utcnow
from app.rate_limiter import check_login_allowed, record_login_failure
from app.sessions import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session,
    delete_session,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# "Remember me": the login name (never a password) in an HttpOnly cookie, so
# the login form can be filled in on this browser next time. How long it and
# the other choices last is the admin's Login times setting.
REMEMBER_COOKIE = "remembered_login"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(default="", max_length=1024)  # may be empty (rules at 0)
    totp_code: str | None = Field(default=None, max_length=10)
    recovery_code: str | None = Field(default=None, max_length=32)
    # Stay logged in (Login times), also after the browser closes.
    keep_logged_in: StrictBool = False
    # Fill the login name in on this browser next time.
    remember_me: StrictBool = False
    # Skip the two-factor code on this browser next time (app/login_times.py).
    remember_device: StrictBool = False


def _fail(db: Session, account: str, ip: str | None) -> HTTPException:
    record_login_failure(account, ip)
    record_event(db, "login_failure", ip_address=ip, details={"reason": "invalid"})
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


@router.post("/login")
def login(
    body: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Password plus a TOTP code or a recovery code (password alone when the
    account has two-factor turned off). One generic error for every failure,
    so the response does not reveal which part was wrong."""
    ip = client_ip(request)
    account = body.email.strip().lower()
    check_login_allowed(account, ip)

    user = authenticate_user(db, body.email.strip(), body.password)
    if user is None:
        raise _fail(db, account, ip)

    if not user.is_totp_enabled:
        # The person turned two-factor off for their account (homes that
        # require it refuse them in require_role). Any code sent is ignored.
        method = "password"
    elif not user.totp_secret:
        raise _fail(db, account, ip)
    elif (
        not body.totp_code
        and not body.recovery_code
        and (device := trusted(db, user.id, request.cookies.get(DEVICE_COOKIE)))
    ):
        # A device the user approved earlier: the password was enough.
        device.last_used_at = utcnow()
        method = "trusted_device"
    elif body.totp_code:
        step = verify_totp_code(body.totp_code, user.totp_secret, user.totp_last_step)
        if step is None:
            raise _fail(db, account, ip)
        user.totp_last_step = step
        method = "totp"
    elif body.recovery_code:
        if not verify_recovery_code(body.recovery_code, db, user.id):
            db.rollback()
            raise _fail(db, account, ip)
        method = "recovery_code"
    else:
        raise _fail(db, account, ip)

    # A choice the admin turned off (blank in Login times) is ignored.
    kept_for = keep_seconds(db)
    keep = body.keep_logged_in and kept_for is not None
    remember_for = remember_me_seconds(db)
    device_for = device_cookie_seconds(db)
    # Commits the TOTP/recovery change too.
    token, csrf = create_session(db, user.id, ip, keep=keep, keep_seconds=kept_for or 0)
    new_device = None
    if (
        body.remember_device
        and device_for is not None
        and method in ("totp", "recovery_code")
    ):
        new_device = remember(db, user.id, request.headers.get("user-agent"), ip)
        record_event(db, "device_remembered", user_id=user.id, ip_address=ip)
    record_event(
        db,
        "login_success",
        user_id=user.id,
        ip_address=ip,
        details={"method": method, "keep_logged_in": keep},
    )
    response = JSONResponse({"csrf_token": csrf})
    # The session cookie is HttpOnly; the CSRF cookie is readable by the web
    # app, which sends it back in the X-CSRF-Token header (double submit).
    # Without "keep me logged in" they are browser-session cookies: closing
    # the browser ends the login.
    for name, value, httponly in (
        (SESSION_COOKIE, token, True),
        (CSRF_COOKIE, csrf, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=kept_for if keep else None,
            path="/",
            secure=True,
            httponly=httponly,
            samesite="strict",
        )
    if new_device:
        response.set_cookie(
            DEVICE_COOKIE,
            new_device,
            max_age=device_for,
            path=DEVICE_PATH,
            secure=True,
            httponly=True,
            samesite="strict",
        )
    if body.remember_me and remember_for is not None:
        response.set_cookie(
            REMEMBER_COOKIE,
            body.email.strip(),
            max_age=remember_for,
            path="/api/v1/auth",
            secure=True,
            httponly=True,
            samesite="strict",
        )
    else:
        response.delete_cookie(
            REMEMBER_COOKIE, path="/api/v1/auth", secure=True, samesite="strict"
        )
    return response


@router.get("/remembered")
def remembered(
    remembered_login: str | None = Cookie(default=None, max_length=255),
    trusted_device: str | None = Cookie(default=None, max_length=100),
    db: Session = Depends(get_db),
) -> dict[str, str | bool | int | None]:
    """The login name this browser asked to remember ("" when none), and
    whether it holds a remembered-device cookie (checked at login, for the
    account that logs in)."""
    row = settings(db)
    remember_on = row.remember_me_days is not None
    return {
        "login": (remembered_login or "").strip() if remember_on else "",
        "device": bool(trusted_device) and row.remember_device_days is not None,
        # Days; 0 = until logging out; None = the choice is off (hidden).
        "keep_days": row.keep_logged_in_days,
        "remember_me": remember_on,
        "remember_device": row.remember_device_days is not None,
    }


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    session: SessionModel = Depends(current_session),
    db: Session = Depends(get_db),
) -> JSONResponse:
    user_id = session.user_id
    delete_session(db, session)
    record_event(db, "logout", user_id=user_id, ip_address=client_ip(request))
    response = JSONResponse({"detail": "Logged out"})
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=True, samesite="strict")
    return response

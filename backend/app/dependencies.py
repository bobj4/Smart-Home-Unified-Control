"""Request dependencies: who is calling, and CSRF checks.

SEC-10: every route except /health and login depends on current_user.
SEC-04: every state-changing route also depends on require_csrf.
"""

import hmac

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db_config import get_db
from app.models import Session as SessionModel
from app.models import User
from app.sessions import CSRF_HEADER, SESSION_COOKIE, get_valid_session


def client_ip(request: Request) -> str | None:
    """The caller's address. Behind the reverse proxy, uvicorn must run with
    --proxy-headers --forwarded-allow-ips=<proxy address> so that this is the
    real client, not the proxy (SEC-26)."""
    return request.client.host if request.client else None


def current_session(request: Request, db: Session = Depends(get_db)) -> SessionModel:
    session = get_valid_session(db, request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return session


def current_user(
    session: SessionModel = Depends(current_session), db: Session = Depends(get_db)
) -> User:
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


def require_csrf(
    request: Request, session: SessionModel = Depends(current_session)
) -> None:
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not hmac.compare_digest(sent, session.csrf_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed")

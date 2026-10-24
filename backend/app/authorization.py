"""Home-scoped authorization (SEC-10 to SEC-12). Deny by default.

Every query for a home's data goes through require_role first.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Home, HomeMembership, Role, User

_RANK = {Role.MEMBER: 1, Role.OPERATOR: 2, Role.ADMIN: 3}


def require_role(
    db: Session, user_id: str, home_id: str, minimum: Role = Role.MEMBER
) -> HomeMembership:
    """Return the caller's membership of the home, or raise.

    404 if the caller is not a member (the home's existence is not revealed),
    403 if their role is below `minimum`. Roles rank admin > operator > member.
    """
    membership = db.scalars(
        select(HomeMembership).where(
            HomeMembership.user_id == user_id, HomeMembership.home_id == home_id
        )
    ).first()
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    try:
        role = Role(membership.role)
    except ValueError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden") from None
    if _RANK[role] < _RANK[minimum]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    home = db.get(Home, home_id)
    user = db.get(User, user_id)
    if (
        home is not None
        and home.require_two_factor
        and not (user and user.is_totp_enabled)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This home requires two-factor login. Turn it on in My account.",
        )
    return membership


def homes_for_user(db: Session, user_id: str) -> list[Home]:
    return list(
        db.scalars(
            select(Home)
            .join(HomeMembership, HomeMembership.home_id == Home.id)
            .where(HomeMembership.user_id == user_id)
            .order_by(Home.name)
        )
    )

"""Each user's order of the rooms on a home's Devices page.

  GET /api/v1/homes/{home_id}/layout   {"room_order": [...]}
  PUT /api/v1/homes/{home_id}/layout   {"room_order": [...]}

Only the order is stored, per user and home; it changes nothing for anyone
else. The thermostats are shown in their own room, "Thermostats", which
starts at the top until the user moves it. Rooms missing from the list
(new ones) follow the listed rooms in name order.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.authorization import require_role
from app.db_config import get_db
from app.dependencies import client_ip, current_user, require_csrf
from app.guest_access import membership, require_guest
from app.models import GUEST_ROLE, Role, RoomLayout, User

router = APIRouter(prefix="/api/v1/homes/{home_id}/layout", tags=["layout"])
THERMOSTATS_ROOM = "Thermostats"
DEFAULT_ORDER = [THERMOSTATS_ROOM]


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_order: list[str] = Field(max_length=200)


def _require_member_or_guest(db: Session, user: User, home_id: str) -> None:
    """Anyone in the home, guests included (it is only their own order)."""
    member = membership(db, user.id, home_id)
    if member is not None and member.role == GUEST_ROLE:
        require_guest(db, user, home_id)
    else:
        require_role(db, user.id, home_id, Role.MEMBER)


def _row(db: Session, user_id: str, home_id: str) -> RoomLayout | None:
    return db.scalars(
        select(RoomLayout).where(
            RoomLayout.user_id == user_id, RoomLayout.home_id == home_id
        )
    ).first()


@router.get("")
def get_layout(
    home_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _require_member_or_guest(db, user, home_id)
    row = _row(db, user.id, home_id)
    order = json.loads(row.room_order) if row else DEFAULT_ORDER
    return {"room_order": order, "thermostats_room": THERMOSTATS_ROOM}


@router.put("", dependencies=[Depends(require_csrf)])
def set_layout(
    home_id: str,
    body: Layout,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_member_or_guest(db, user, home_id)
    order = []
    for name in body.room_order:
        if not isinstance(name, str) or len(name) > 50:
            raise HTTPException(422, "Room names are at most 50 characters")
        if name not in order:
            order.append(name)
    row = _row(db, user.id, home_id)
    if row is None:
        row = RoomLayout(user_id=user.id, home_id=home_id)
        db.add(row)
    row.room_order = json.dumps(order)
    db.commit()
    record_event(
        db,
        "room_layout_changed",
        user_id=user.id,
        home_id=home_id,
        ip_address=client_ip(request),
        details={"rooms": len(order)},
    )
    return {"room_order": order, "thermostats_room": THERMOSTATS_ROOM}

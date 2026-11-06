"""Each user's order of the rooms on a home's Devices page.

  GET /api/v1/homes/{home_id}/layout?screen=phone|wide
  PUT /api/v1/homes/{home_id}/layout   {"room_order"?, "collapsed"?, "screen"?}

Stored per user, home and screen type ("phone" or "wide"), with the rooms
the user folded shut; it changes nothing for anyone
else. The thermostats are shown in their own room, "Thermostats", which
starts at the top until the user moves it. Rooms missing from the list
(new ones) follow the listed rooms in name order.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
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


Screen = Literal["phone", "wide"]


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=100)
    type: str = Field(default="", max_length=30, pattern=r"^[a-z_]*$")
    on: StrictBool = False


class Grid(BaseModel):
    """Rooms side by side: how many columns, and how many each room spans."""

    model_config = ConfigDict(extra="forbid")
    columns: int = Field(ge=1, le=4)
    sizes: dict[str, int] = Field(default_factory=dict, max_length=200)


def _grid(body: Grid) -> dict[str, Any]:
    for room, span in body.sizes.items():
        if len(room) > 50 or not 1 <= span <= 4:
            raise HTTPException(422, "Each room is 1 to 4 columns wide")
    return {"columns": body.columns, "sizes": body.sizes}


def _default_grid(screen: str) -> dict[str, Any]:
    return {"columns": 1 if screen == "phone" else 2, "sizes": {}}


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_order: list[str] | None = Field(default=None, max_length=200)
    collapsed: list[str] | None = Field(default=None, max_length=200)
    filters: Filters | None = None
    thermostats_apart: StrictBool | None = None
    doors_apart: StrictBool | None = None
    grid: Grid | None = None
    screen: Screen = "wide"


def _require_member_or_guest(db: Session, user: User, home_id: str) -> None:
    """Anyone in the home, guests included (it is only their own order)."""
    member = membership(db, user.id, home_id)
    if member is not None and member.role == GUEST_ROLE:
        require_guest(db, user, home_id)
    else:
        require_role(db, user.id, home_id, Role.MEMBER)


def _row(db: Session, user_id: str, home_id: str, screen: str) -> RoomLayout | None:
    return db.scalars(
        select(RoomLayout).where(
            RoomLayout.user_id == user_id,
            RoomLayout.home_id == home_id,
            RoomLayout.screen == screen,
        )
    ).first()


def _names(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        if not isinstance(name, str) or len(name) > 50:
            raise HTTPException(422, "Room names are at most 50 characters")
        if name not in out:
            out.append(name)
    return out


def _out(db: Session, user_id: str, home_id: str, screen: str) -> dict[str, Any]:
    row = _row(db, user_id, home_id, screen)
    # A phone with no layout of its own starts from the wide-screen order.
    fallback = row or (
        _row(db, user_id, home_id, "wide") if screen == "phone" else None
    )
    return {
        "room_order": json.loads(fallback.room_order) if fallback else DEFAULT_ORDER,
        "collapsed": json.loads(row.collapsed) if row and row.collapsed else [],
        "filters": json.loads(row.filters)
        if row and row.filters
        else Filters().model_dump(),
        "screen": screen,
        "thermostats_apart": bool(row.thermostats_apart) if row else False,
        "doors_apart": bool(row.doors_apart) if row else False,
        "grid": json.loads(row.grid) if row and row.grid else _default_grid(screen),
        "thermostats_room": THERMOSTATS_ROOM,
    }


@router.get("")
def get_layout(
    home_id: str,
    screen: Screen = "wide",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_member_or_guest(db, user, home_id)
    return _out(db, user.id, home_id, screen)


@router.put("", dependencies=[Depends(require_csrf)])
def set_layout(
    home_id: str,
    body: Layout,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The room order, the folded rooms, or both, for one screen type."""
    _require_member_or_guest(db, user, home_id)
    changes = (
        body.room_order,
        body.collapsed,
        body.filters,
        body.thermostats_apart,
        body.doors_apart,
        body.grid,
    )
    if all(change is None for change in changes):
        raise HTTPException(
            422,
            "Send room_order, collapsed, filters, thermostats_apart or doors_apart",
        )
    current = _out(db, user.id, home_id, body.screen)
    row = _row(db, user.id, home_id, body.screen)
    if row is None:
        row = RoomLayout(
            user_id=user.id,
            home_id=home_id,
            screen=body.screen,
            room_order=json.dumps(current["room_order"]),
        )
        db.add(row)
    if body.room_order is not None:
        row.room_order = json.dumps(_names(body.room_order))
    if body.collapsed is not None:
        row.collapsed = json.dumps(_names(body.collapsed))
    if body.filters is not None:
        row.filters = json.dumps(body.filters.model_dump())
    if body.thermostats_apart is not None:
        row.thermostats_apart = body.thermostats_apart
    if body.doors_apart is not None:
        row.doors_apart = body.doors_apart
    if body.grid is not None:
        row.grid = json.dumps(_grid(body.grid))
    db.commit()
    if body.room_order is not None:  # folding a room open or shut is not audited
        record_event(
            db,
            "room_layout_changed",
            user_id=user.id,
            home_id=home_id,
            ip_address=client_ip(request),
            details={"rooms": len(body.room_order), "screen": body.screen},
        )
    return _out(db, user.id, home_id, body.screen)

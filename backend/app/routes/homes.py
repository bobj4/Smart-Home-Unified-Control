"""Homes the caller belongs to."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.authorization import homes_for_user
from app.db_config import get_db
from app.dependencies import current_user
from app.models import User

router = APIRouter(prefix="/api/v1/homes", tags=["homes"])


@router.get("")
def list_homes(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict[str, str]]:
    return [{"id": h.id, "name": h.name} for h in homes_for_user(db, user.id)]

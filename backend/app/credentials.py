"""Store, read and remove a home's encrypted login for an integration."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import vault
from app.models import IntegrationCredential


def _row(db: Session, home_id: str, integration: str) -> IntegrationCredential | None:
    return db.scalars(
        select(IntegrationCredential).where(
            IntegrationCredential.home_id == home_id,
            IntegrationCredential.integration == integration,
        )
    ).first()


def label(db: Session, home_id: str, integration: str) -> str | None:
    row = _row(db, home_id, integration)
    return row.label if row else None


def load(db: Session, home_id: str, integration: str) -> dict[str, Any] | None:
    """The decrypted login, or None if none is saved. Raises vault.VaultError."""
    row = _row(db, home_id, integration)
    return vault.decrypt(row.secret) if row else None


def save(
    db: Session, home_id: str, integration: str, label: str, data: dict[str, Any]
) -> None:
    secret = vault.encrypt(data)  # raises VaultError before anything is written
    row = _row(db, home_id, integration)
    if row is None:
        row = IntegrationCredential(home_id=home_id, integration=integration)
        db.add(row)
    row.label = label
    row.secret = secret
    db.commit()


def remove(db: Session, home_id: str, integration: str) -> bool:
    row = _row(db, home_id, integration)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True

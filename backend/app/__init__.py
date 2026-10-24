"""Smart home backend application package."""

import os
from pathlib import Path

from sqlalchemy import inspect

from . import db_config, models

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def trust_public_roots() -> None:
    """Outbound HTTPS trusts the public root certificates (certifi) as well as
    the operating system's. Windows downloads some roots only when its own
    programs first need one, into a store Python does not read, so Python can
    lack the root a vendor has just moved to (Rheem's EcoNet server, 2026-10:
    "self-signed certificate in certificate chain"). Certificates are still
    fully checked. Runs on import, before any HTTPS client builds its
    default context; an SSL_CERT_FILE set by the owner is kept."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


trust_public_roots()


def init_db() -> None:
    """Bring the database schema up to date.

    A new or Alembic-managed database is migrated to the latest revision.
    A database whose tables were created without Alembic (the test suite does
    this) only gets missing tables created.
    """
    tables = set(inspect(db_config.engine).get_table_names())
    if tables and "alembic_version" not in tables:
        models.Base.metadata.create_all(bind=db_config.engine)
        return

    from alembic.config import Config

    from alembic import command

    config = Config(str(ALEMBIC_INI))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


__all__ = ["init_db", "models"]

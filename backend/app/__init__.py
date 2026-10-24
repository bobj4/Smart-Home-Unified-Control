"""Smart home backend application package."""

from pathlib import Path

from sqlalchemy import inspect

from . import db_config, models

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


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

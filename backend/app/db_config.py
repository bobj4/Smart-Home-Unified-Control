"""Settings and database setup."""

from collections.abc import Iterator

from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Settings(BaseSettings):
    """Application settings, read from environment variables."""

    DATABASE_URL: str = "sqlite:///./smart_home.db"

    # Sessions (SEC-03): 30 minutes idle, 12 hours in total.
    IDLE_TIMEOUT_SECONDS: int = 30 * 60
    TOTAL_TIMEOUT_SECONDS: int = 12 * 60 * 60
    # "Keep me logged in" on the login page (owner-approved 2026-10-24).
    KEEP_LOGGED_IN_SECONDS: int = 30 * 24 * 60 * 60

    # Login methods (comma-separated): password, passkey, oidc.
    LOGIN_METHODS: str = "password"

    # Allowed browser origins for CORS, comma-separated. Empty by default (SEC-14).
    CORS_ORIGINS: str = ""

    # Live state: seconds between background reads of real devices; 0 = off.
    REFRESH_SECONDS: int = 30

    # Database backups (app/backup.py): every BACKUP_HOURS (0 = never), the
    # newest BACKUP_KEEP kept, in BACKUP_DIR (default: backups next to the db).
    BACKUP_HOURS: float = 24
    BACKUP_KEEP: int = 14
    BACKUP_DIR: str = ""

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def enabled_login_methods(self) -> list[str]:
        return [m.strip() for m in self.LOGIN_METHODS.split(",") if m.strip()]


settings = Settings()

_connect_args = (
    {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
)
engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

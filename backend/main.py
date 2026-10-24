"""Smart home backend: FastAPI application."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import backup, cync_live, init_db, refresh
from app.db_config import settings
from app.headers import SecurityHeadersMiddleware
from app.routes import (
    account,
    admin,
    audit_log,
    auth,
    cync,
    devices,
    email_admin,
    frigate,
    groups,
    home_security,
    homes,
    https_admin,
    integrations,
    member_access,
    members,
    rheem,
    safety_limits,
    samsung,
    thermostat,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# Only files that exist in web/js and web/css when the app starts are served.
WEB_SCRIPTS = {p.name for p in (WEB_DIR / "js").glob("*.js")}
WEB_STYLES = {p.name for p in (WEB_DIR / "css").glob("*.css")}
WEB_ICONS = {p.name for p in (WEB_DIR / "icons").glob("*.png")}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    task = (
        asyncio.create_task(refresh.run_forever(settings.REFRESH_SECONDS))
        if settings.REFRESH_SECONDS > 0
        else None
    )
    live = (
        asyncio.create_task(cync_live.run_forever())
        if settings.REFRESH_SECONDS > 0
        else None
    )
    backups = (
        asyncio.create_task(backup.run_forever(settings.BACKUP_HOURS))
        if settings.BACKUP_HOURS > 0 and settings.DATABASE_URL.startswith("sqlite")
        else None
    )
    yield
    for running in (task, live, backups):
        if running is not None:
            running.cancel()


# API docs are off (M8): they would describe every route to anyone.
app = FastAPI(
    title="Smart Home Backend",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# No origins are allowed unless CORS_ORIGINS lists them (SEC-14).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(homes.router)
app.include_router(devices.router)
app.include_router(groups.router)
app.include_router(groups.home_router)
app.include_router(safety_limits.router)
app.include_router(account.router)
app.include_router(admin.public_router)
app.include_router(admin.router)
app.include_router(https_admin.router)
app.include_router(email_admin.router)
app.include_router(email_admin.public_router)
app.include_router(members.router)
app.include_router(members.enroll_router)
app.include_router(member_access.router)
app.include_router(audit_log.router)
app.include_router(integrations.router)
app.include_router(rheem.router)
app.include_router(rheem.usage_router)
app.include_router(thermostat.router)
app.include_router(cync.router)
app.include_router(home_security.router)
app.include_router(samsung.router)
app.include_router(frigate.settings_router)
app.include_router(frigate.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health", tags=["health"])
def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "smart-home-backend"}


# Web app (PWA). Served without a session so the login page can load.
@app.get("/", include_in_schema=False)
def web_index() -> FileResponse:
    return FileResponse(WEB_DIR / "public" / "index.html", media_type="text/html")


@app.get("/js/{name}", include_in_schema=False)
def web_script(name: str) -> FileResponse:
    if name not in WEB_SCRIPTS:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(WEB_DIR / "js" / name, media_type="text/javascript")


@app.get("/css/{name}", include_in_schema=False)
def web_style(name: str) -> FileResponse:
    if name not in WEB_STYLES:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(WEB_DIR / "css" / name, media_type="text/css")


@app.get("/icons/{name}", include_in_schema=False)
def web_icon(name: str) -> FileResponse:
    if name not in WEB_ICONS:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(WEB_DIR / "icons" / name, media_type="image/png")


@app.get("/manifest.json", include_in_schema=False)
def web_manifest() -> FileResponse:
    return FileResponse(
        WEB_DIR / "manifest.json", media_type="application/manifest+json"
    )

"""FastAPI app: a Settings page gated by login, and a read-only Dashboard
that stays open on the LAN. No SPA — server-rendered Jinja2 throughout.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from skytracer.web import routes_auth, routes_chat, routes_dashboard, routes_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Skytracer")
    app.mount(
        "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
    )
    app.include_router(routes_auth.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_dashboard.router)
    app.include_router(routes_chat.router)
    return app

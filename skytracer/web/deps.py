"""FastAPI dependencies: a fresh SQLite connection per request (sqlite3
connections aren't shared-safe across threads, and a connection-per-request
is cheap and matches how the CLI already works), plus the auth gates that
protect Settings while leaving the Dashboard open on the LAN.

Route modules should take a connection via the `ConnDep` / `SettingsConnDep`
Annotated aliases below rather than writing `Depends(...)` inline — that's
the FastAPI-recommended style and avoids ruff's B008 (function call in a
default argument), which would otherwise fire on every single route.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException
from starlette.requests import Request

from skytracer import settings_store
from skytracer.bootstrap import BootstrapError, ensure_seeded
from skytracer.db import init_db
from skytracer.paths import resolve_db_path
from skytracer.web.auth import SESSION_COOKIE_NAME, is_logged_in

ADMIN_PASSWORD_KEY = "web.admin_password"


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = init_db(resolve_db_path())
    try:
        ensure_seeded(conn)
    except BootstrapError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        yield conn
    finally:
        conn.close()


def has_admin_password(conn: sqlite3.Connection) -> bool:
    return bool(settings_store.get(conn, ADMIN_PASSWORD_KEY, ""))


def require_settings_access(
    request: Request, conn: Annotated[sqlite3.Connection, Depends(get_conn)]
) -> sqlite3.Connection:
    """Gate for every Settings-mutating route: no password yet -> /setup;
    password set but not logged in -> /login; otherwise let the request
    through with its connection.
    """
    if not has_admin_password(conn):
        raise HTTPException(status_code=303, headers={"Location": "/setup"})
    if not is_logged_in(conn, request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return conn


ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]
SettingsConnDep = Annotated[sqlite3.Connection, Depends(require_settings_access)]

__all__ = [
    "SESSION_COOKIE_NAME",
    "ConnDep",
    "SettingsConnDep",
    "get_conn",
    "has_admin_password",
    "require_settings_access",
]

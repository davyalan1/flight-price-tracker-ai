"""SQLite schema management. Idempotent: safe to call init_db on every start."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    route_key TEXT NOT NULL,
    origin TEXT,
    destination TEXT,
    depart_date TEXT,
    return_date TEXT,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    airlines TEXT,
    stops INTEGER,
    route TEXT,
    deep_link TEXT,
    source TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_obs_routekey_time ON observations(route_key, observed_at);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY,
    sent_at TEXT NOT NULL,
    route_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    price REAL NOT NULL
);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the web app's per-request connection (see
    # web/deps.py) is opened by a sync dependency (run in a worker thread)
    # and then used from the request handler, which for `async def` routes
    # runs on the event loop thread instead — a different OS thread. Each
    # connection is still only ever touched by one request at a time, so
    # this is the documented-safe use of the flag, not a concurrency bug.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive schema changes for databases created before this column
    existed — CREATE TABLE IF NOT EXISTS above only helps brand-new DBs.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}
    if "rank" not in cols:
        conn.execute("ALTER TABLE observations ADD COLUMN rank INTEGER NOT NULL DEFAULT 0")

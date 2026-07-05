from __future__ import annotations

import sqlite3

from skytracer.db import init_db


def test_init_db_adds_rank_column_to_a_pre_phase10_database(tmp_path) -> None:
    """Simulates the real, already-live database: created before the `rank`
    column existed. init_db must additively migrate it, not just rely on
    CREATE TABLE IF NOT EXISTS (which does nothing for an existing table).
    """
    db_path = tmp_path / "skytracer.db"
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY,
            observed_at TEXT NOT NULL,
            route_key TEXT NOT NULL,
            origin TEXT, destination TEXT, depart_date TEXT, return_date TEXT,
            price REAL NOT NULL, currency TEXT NOT NULL, airlines TEXT,
            stops INTEGER, route TEXT, deep_link TEXT, source TEXT NOT NULL
        )
        """
    )
    old_conn.execute(
        "INSERT INTO observations (observed_at, route_key, price, currency, source) "
        "VALUES ('2026-01-01T00:00:00+00:00', 'k', 500.0, 'USD', 'google')"
    )
    old_conn.commit()
    old_conn.close()

    conn = init_db(db_path)
    row = conn.execute("SELECT rank FROM observations WHERE route_key = 'k'").fetchone()
    assert row["rank"] == 0  # pre-existing rows must resolve to the "winner" rank


def test_init_db_is_idempotent_on_a_fresh_database(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    init_db(db_path)
    conn = init_db(db_path)  # re-run, as every real startup does
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}
    assert "rank" in cols

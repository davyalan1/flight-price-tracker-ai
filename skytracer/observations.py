"""Persisting and reading back fare observations. Schema is defined in
db.py; this module knows how to turn a FareResult into a row and back.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from skytracer.models import FareResult, PricePoint, SearchQuery


def insert_observation(
    conn: sqlite3.Connection,
    *,
    route_key: str,
    query: SearchQuery,
    result: FareResult,
    observed_at: str | None = None,
    rank: int = 0,
) -> None:
    observed_at = observed_at or datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO observations (
            observed_at, route_key, origin, destination, depart_date, return_date,
            price, currency, airlines, stops, route, deep_link, source, rank
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_at,
            route_key,
            query.origin,
            query.destination,
            query.depart_date,
            query.return_date,
            result.price,
            result.currency,
            json.dumps(result.airlines),
            result.stops,
            result.route,
            result.deep_link,
            result.source,
            rank,
        ),
    )
    conn.commit()


def fetch_price_points(conn: sqlite3.Connection, route_key: str) -> list[PricePoint]:
    """All rank-0 (the winner of each poll) observations for a route_key,
    oldest first — the raw material for stats.compute_stats() and
    alerts.evaluate_alert_reasons(). Rank>0 rows (Phase 10's extra
    top-N-per-poll fares) must stay excluded here or a single poll's 2nd/3rd
    cheapest fares would corrupt all-time-low/trend history.
    """
    rows = conn.execute(
        "SELECT observed_at, price FROM observations "
        "WHERE route_key = ? AND rank = 0 ORDER BY observed_at ASC",
        (route_key,),
    ).fetchall()
    return [PricePoint(observed_at=row["observed_at"], price=row["price"]) for row in rows]


def fetch_top_n_for_latest_poll(
    conn: sqlite3.Connection, route_key: str, n: int
) -> list[sqlite3.Row]:
    """The best `n` fares from the most recent poll of this route, cheapest
    first — powers the dashboard's "best fares right now" widget.
    """
    latest = conn.execute(
        "SELECT observed_at FROM observations WHERE route_key = ? AND rank = 0 "
        "ORDER BY observed_at DESC LIMIT 1",
        (route_key,),
    ).fetchone()
    if latest is None:
        return []
    return conn.execute(
        "SELECT * FROM observations WHERE route_key = ? AND observed_at = ? "
        "ORDER BY rank ASC LIMIT ?",
        (route_key, latest["observed_at"], n),
    ).fetchall()


def list_route_keys(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT route_key FROM observations ORDER BY route_key").fetchall()
    return [row["route_key"] for row in rows]


def fetch_latest_observation(conn: sqlite3.Connection, route_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM observations WHERE route_key = ? AND rank = 0 "
        "ORDER BY observed_at DESC LIMIT 1",
        (route_key,),
    ).fetchone()


def fetch_observations(
    conn: sqlite3.Connection, route_key: str, limit: int = 50
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM observations WHERE route_key = ? AND rank = 0 "
        "ORDER BY observed_at DESC LIMIT ?",
        (route_key, limit),
    ).fetchall()

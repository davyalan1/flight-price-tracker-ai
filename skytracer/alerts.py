"""Alert decision logic. The two functions that matter for correctness —
evaluate_alert_reasons and should_send_alert — are pure and take no DB
connection, per spec: alert-decision logic must be unit-testable with plain
seeded data. The rest of this module is thin DB plumbing around alert_log.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from skytracer.config import AlertsConfig
from skytracer.models import PricePoint

REASON_THRESHOLD = "threshold"
REASON_NEW_LOW = "new_low"
REASON_DROP = "drop"


def evaluate_alert_reasons(
    points: list[PricePoint],
    *,
    threshold_price: float,
    drop_percent: float,
    notify_on_new_low: bool,
) -> list[str]:
    """Which alert conditions does the most recent point trigger?

    `points` must be sorted oldest-first (see observations.fetch_price_points).
    """
    if not points:
        return []

    current = points[-1]
    prior_prices = [p.price for p in points[:-1]]
    reasons: list[str] = []

    if current.price <= threshold_price:
        reasons.append(REASON_THRESHOLD)

    if notify_on_new_low and prior_prices and current.price < min(prior_prices):
        reasons.append(REASON_NEW_LOW)

    if prior_prices:
        previous_price = prior_prices[-1]
        if previous_price > 0:
            drop = (previous_price - current.price) / previous_price * 100
            if drop >= drop_percent:
                reasons.append(REASON_DROP)

    return reasons


def should_send_alert(
    reasons: list[str],
    *,
    last_alert_sent_at: str | None,
    cooldown_hours: float,
    now: datetime | None = None,
) -> bool:
    """Cooldown gate: even a triggered reason is suppressed if the last alert
    for this route (any reason) was sent too recently.
    """
    if not reasons:
        return False
    if last_alert_sent_at is None:
        return True
    elapsed = (now or datetime.now(UTC)) - datetime.fromisoformat(last_alert_sent_at)
    return elapsed.total_seconds() >= cooldown_hours * 3600


def get_last_alert_sent_at(conn: sqlite3.Connection, route_key: str) -> str | None:
    row = conn.execute(
        "SELECT sent_at FROM alert_log WHERE route_key = ? ORDER BY sent_at DESC LIMIT 1",
        (route_key,),
    ).fetchone()
    return row["sent_at"] if row else None


def fetch_alert_history(
    conn: sqlite3.Connection, route_key: str, limit: int = 20
) -> list[sqlite3.Row]:
    """Most recent alerts sent for a route, newest first — powers the
    dashboard's alert-history timeline.
    """
    return conn.execute(
        "SELECT * FROM alert_log WHERE route_key = ? ORDER BY sent_at DESC LIMIT ?",
        (route_key, limit),
    ).fetchall()


def log_alert(
    conn: sqlite3.Connection,
    *,
    route_key: str,
    reason: str,
    price: float,
    sent_at: str | None = None,
) -> None:
    sent_at = sent_at or datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO alert_log (sent_at, route_key, reason, price) VALUES (?, ?, ?, ?)",
        (sent_at, route_key, reason, price),
    )
    conn.commit()


def decide_alert(
    conn: sqlite3.Connection,
    *,
    route_key: str,
    points: list[PricePoint],
    config: AlertsConfig,
    now: datetime | None = None,
) -> list[str]:
    """Which reasons are triggered AND clear of the cooldown? Read-only —
    does not write to alert_log. The caller (poller) should only call
    record_alert_sent() *after* actually delivering the notification, so a
    failed send doesn't silently burn the cooldown window (see poller.py).
    """
    reasons = evaluate_alert_reasons(
        points,
        threshold_price=config.threshold_price,
        drop_percent=config.drop_percent,
        notify_on_new_low=config.notify_on_new_low,
    )
    if not reasons:
        return []

    last_sent_at = get_last_alert_sent_at(conn, route_key)
    if not should_send_alert(
        reasons, last_alert_sent_at=last_sent_at, cooldown_hours=config.cooldown_hours, now=now
    ):
        return []
    return reasons


def record_alert_sent(
    conn: sqlite3.Connection,
    *,
    route_key: str,
    reasons: list[str],
    price: float,
    sent_at: str | None = None,
) -> None:
    """Log one alert_log row per reason — call only after a successful
    notification send, since this is what starts the cooldown clock.
    """
    sent_at = sent_at or datetime.now(UTC).isoformat()
    for reason in reasons:
        log_alert(conn, route_key=route_key, reason=reason, price=price, sent_at=sent_at)

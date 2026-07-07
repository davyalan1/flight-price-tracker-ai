"""Ties settings + fare sources + storage + alerts + notifications together
for `skytracer poll`.

Phase 2 added Google-only fetch/storage. Phase 3 added alert evaluation and
a consecutive-failure watchdog. Phase 4 added real notification delivery for
both triggered price alerts and a "tracker is broken" signal. Phase 6 added
the orchestrator so every enabled source (not just Google) is queried and the
cheapest valid result across all of them wins. Phase 7 added real
scan_step_days-bounded date sampling for flexible-window trips. Phase 9 added
is_poll_due so the systemd timer can fire on a short fixed cadence while
schedule.every_hours (edited on the Settings page, not systemd) controls how
often a poll actually happens.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta

from skytracer import alerts, settings_store, stats, watchdog
from skytracer.config import Config, TripConfig, TripEntry
from skytracer.models import Alert, FareResult, SearchQuery, route_key_for_trip
from skytracer.notify import build_notifier
from skytracer.observations import fetch_price_points, insert_observation
from skytracer.settings_store import as_config
from skytracer.sources.orchestrator import build_enabled_sources, search_all

logger = logging.getLogger("skytracer.poller")

LAST_POLL_AT_KEY = "internal.last_poll_at"


def is_poll_due(conn: sqlite3.Connection, config: Config, now: datetime | None = None) -> bool:
    """Whether enough time has passed since the last poll attempt, per the
    live schedule.every_hours setting — not a fixed systemd interval, so
    changing the schedule on the Settings page takes effect on the next
    timer tick instead of requiring an operator to edit/reload systemd.
    """
    last = settings_store.get(conn, LAST_POLL_AT_KEY, None)
    if not last:
        return True
    elapsed = (now or datetime.now(UTC)) - datetime.fromisoformat(last)
    return elapsed >= timedelta(hours=config.schedule.every_hours)


def _resolve_queries(trip: TripConfig) -> list[SearchQuery]:
    """A fixed trip searches its exact dates — one query. A flexible trip
    samples every scan_step_days across [earliest_depart, latest_depart],
    each paired with a trip_length_days-later return date — one query per
    sampled departure date, bounding the request count per poll instead of
    scanning every single day in the window.
    """
    base = {
        "origin": trip.origin,
        "destination": trip.destination,
        "adults": trip.adults,
        "cabin": trip.cabin,
        "currency": trip.currency,
    }
    if trip.fixed.enabled:
        return [
            SearchQuery(
                depart_date=trip.fixed.depart_date,
                return_date=trip.fixed.return_date or None,
                **base,
            )
        ]

    earliest = date.fromisoformat(trip.flexible.earliest_depart)
    latest = date.fromisoformat(trip.flexible.latest_depart)
    step = timedelta(days=trip.flexible.scan_step_days)
    trip_length = timedelta(days=trip.flexible.trip_length_days)

    queries = []
    depart = earliest
    while depart <= latest:
        queries.append(
            SearchQuery(
                depart_date=depart.isoformat(),
                return_date=(depart + trip_length).isoformat(),
                **base,
            )
        )
        depart += step
    return queries


def _note_failure(conn: sqlite3.Connection, config: Config) -> None:
    count = watchdog.record_failure(conn)
    if not watchdog.is_broken(count):
        return
    logger.error(
        "poll: tracker has failed %d consecutive times in a row — something is broken "
        "and needs attention",
        count,
    )
    # Fire once at the exact crossing point, not on every failure after —
    # otherwise a multi-day outage would spam the channel once per poll.
    if count != watchdog.CONSECUTIVE_FAILURE_THRESHOLD:
        return
    message = (
        f"Skytracer tracker is broken: {count} consecutive poll failures. "
        "Check `journalctl -u skytracer-poll` for details."
    )
    try:
        build_notifier(config.notify).send_text(message)
    except Exception:
        logger.exception(
            "poll: failed to send tracker-broken notification via %s", config.notify.channel
        )


def _poll_trip(
    conn: sqlite3.Connection, config: Config, entry: TripEntry, sources: list
) -> bool:
    """Search, store (top-N), and alert for one tracked trip. Returns
    whether it found (and stored) at least one fare — False just means this
    trip's search came up empty, not that the whole poll failed (see
    run_poll_once, which only fires the "tracker is broken" watchdog if
    every trip fails)."""
    queries = _resolve_queries(entry.trip)
    logger.info(
        "poll: searching %d source(s) across %d sampled date(s) for %s -> %s",
        len(sources),
        len(queries),
        entry.trip.origin,
        entry.trip.destination,
    )
    results: list[tuple[SearchQuery, FareResult]] = [
        (query, fare) for query in queries for fare in search_all(sources, query)
    ]
    if not results:
        logger.warning(
            "poll: no enabled source returned any fares for %s -> %s across %d sampled date(s)",
            entry.trip.origin,
            entry.trip.destination,
            len(queries),
        )
        return False

    results.sort(key=lambda pair: pair[1].price)
    route_key = route_key_for_trip(entry.trip)
    observed_at = datetime.now(UTC).isoformat()
    top_n = results[: config.dashboard.top_n_fares]
    for rank, (query, fare) in enumerate(top_n):
        insert_observation(
            conn,
            route_key=route_key,
            query=query,
            result=fare,
            observed_at=observed_at,
            rank=rank,
        )
    query, cheapest = top_n[0]

    logger.info(
        "poll: stored %s %.2f via %s (%d stop(s), route %s) — %s",
        cheapest.currency,
        cheapest.price,
        cheapest.source,
        cheapest.stops,
        cheapest.route,
        cheapest.deep_link,
    )

    points = fetch_price_points(conn, route_key)
    fired = alerts.decide_alert(conn, route_key=route_key, points=points, config=entry.alerts)
    if not fired:
        return True

    logger.info(
        "poll: alert(s) triggered for %s: %s (price %.2f)",
        route_key,
        ", ".join(fired),
        cheapest.price,
    )
    route_stats = stats.compute_stats(route_key, points)
    alert = Alert(
        route_key=route_key,
        route=cheapest.route,
        price=cheapest.price,
        currency=cheapest.currency,
        reasons=fired,
        all_time_low=route_stats.all_time_low,
        deep_link=cheapest.deep_link,
        dashboard_url=f"http://{config.web.host}:{config.web.port}/route/{route_key}",
    )
    try:
        notifier = build_notifier(config.notify)
        notifier.send(alert)
        logger.info("poll: notification sent via %s", config.notify.channel)
    except Exception:
        logger.exception(
            "poll: failed to send notification via %s — not logging to alert_log so this "
            "retries next poll instead of silently eating the cooldown window",
            config.notify.channel,
        )
        return True

    # Only start the cooldown clock once delivery actually succeeded.
    alerts.record_alert_sent(conn, route_key=route_key, reasons=fired, price=cheapest.price)
    return True


def run_poll_once(conn: sqlite3.Connection) -> None:
    config = as_config(conn)
    # Stamped unconditionally (even on later failure) so pacing is based on
    # the last *attempt*, not the last success — otherwise a broken source
    # would make is_poll_due() true on every single systemd timer tick.
    settings_store.set(conn, LAST_POLL_AT_KEY, datetime.now(UTC).isoformat())

    if not config.trips:
        logger.info("poll: no trips configured — nothing to do")
        return

    sources = build_enabled_sources(config.sources)
    if not sources:
        logger.error("poll: no fare sources are enabled — nothing to do")
        _note_failure(conn, config)
        return

    # A poll only counts as a full failure (tripping the watchdog) if every
    # tracked trip came up empty — one route having a bad night shouldn't
    # spam a "tracker is broken" alert while the others are working fine.
    succeeded = [_poll_trip(conn, config, entry, sources) for entry in config.trips]
    if not any(succeeded):
        _note_failure(conn, config)
        return
    watchdog.record_success(conn)
    if not all(succeeded):
        logger.warning(
            "poll: %d of %d trip(s) failed to return a fare this cycle",
            succeeded.count(False),
            len(succeeded),
        )

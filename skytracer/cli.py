"""Skytracer CLI: poll, show, test-notify, run-web."""

from __future__ import annotations

import logging
import sqlite3

import typer
import uvicorn

from skytracer import stats as stats_module
from skytracer.bootstrap import BootstrapError, ensure_seeded
from skytracer.db import init_db
from skytracer.logging_conf import configure_logging
from skytracer.models import Alert
from skytracer.notify import build_notifier
from skytracer.observations import fetch_price_points, list_route_keys
from skytracer.paths import resolve_db_path
from skytracer.poller import is_poll_due, run_poll_once
from skytracer.settings_store import as_config

app = typer.Typer(help="Skytracer: a self-hosted flight-price tracker.")
logger = logging.getLogger("skytracer.cli")


def bootstrap() -> sqlite3.Connection:
    """Init logging + DB, seeding settings from config.toml on first run."""
    configure_logging()
    conn = init_db(resolve_db_path())
    try:
        ensure_seeded(conn)
    except BootstrapError as exc:
        raise typer.Exit(code=1) from exc
    return conn


@app.command()
def poll(
    once: bool = typer.Option(
        True,
        "--once",
        help="Run a single poll and exit (the only supported mode — the systemd "
        "timer, not an internal loop, drives the schedule).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Poll now even if schedule.every_hours hasn't elapsed since the last attempt.",
    ),
) -> None:
    """Poll all enabled fare sources and store the cheapest result.

    The systemd timer fires this frequently (see systemd/skytracer-poll.timer);
    whether a poll actually happens is gated by schedule.every_hours from the
    Settings page, not by the timer's own interval — so changing the schedule
    takes effect on the next tick with no systemd edit required.
    """
    conn = bootstrap()
    config = as_config(conn)
    if not force and not is_poll_due(conn, config):
        logger.info(
            "poll: not due yet (schedule.every_hours=%s) — skipping", config.schedule.every_hours
        )
        return
    run_poll_once(conn)


@app.command()
def show() -> None:
    """Print current tracked routes and stats."""
    conn = bootstrap()
    route_keys = list_route_keys(conn)
    if not route_keys:
        print("No observations yet — run `skytracer poll` or wait for the first scheduled poll.")
        return
    for route_key in route_keys:
        points = fetch_price_points(conn, route_key)
        route_stats = stats_module.compute_stats(route_key, points)
        if route_stats is None:
            continue
        print(
            f"{route_key}: current {route_stats.current_price:.2f} "
            f"(all-time low {route_stats.all_time_low:.2f}, trend {route_stats.trend}, "
            f"last updated {route_stats.current_observed_at})"
        )


@app.command(name="test-notify")
def test_notify() -> None:
    """Send a test notification through the configured channel."""
    conn = bootstrap()
    config = as_config(conn)
    first_trip = config.trips[0].trip if config.trips else None
    route = (
        f"{first_trip.origin} → {first_trip.destination} (test)"
        if first_trip
        else "No trips configured (test)"
    )
    alert = Alert(
        route_key="test",
        route=route,
        price=999.0,
        currency=first_trip.currency if first_trip else "USD",
        reasons=["test"],
        all_time_low=999.0,
        deep_link="https://www.google.com/travel/flights",
        dashboard_url=f"http://{config.web.host}:{config.web.port}/",
    )
    try:
        notifier = build_notifier(config.notify)
        notifier.send(alert)
    except Exception:
        logger.exception("test-notify: failed to send via %s", config.notify.channel)
        raise typer.Exit(code=1) from None
    logger.info("test-notify: sent a test message via %s", config.notify.channel)


@app.command(name="run-web")
def run_web() -> None:
    """Run the web UI (Settings + Dashboard)."""
    conn = bootstrap()
    config = as_config(conn)
    conn.close()

    from skytracer.web import create_app

    uvicorn.run(create_app(), host=config.web.host, port=config.web.port)


@app.command(name="run-telegram-bot")
def run_telegram_bot() -> None:
    """Run the Telegram conversational bot (long-polling). Requires
    ai.telegram_bot_token to be set on the Settings page.
    """
    _run_bot("run-telegram-bot", "telegram_bot_token", "skytracer.bots.telegram_bot")


@app.command(name="run-discord-bot")
def run_discord_bot() -> None:
    """Run the Discord conversational bot. Requires ai.discord_bot_token to
    be set on the Settings page.
    """
    _run_bot("run-discord-bot", "discord_bot_token", "skytracer.bots.discord_bot")


def _run_bot(command_name: str, token_field: str, module_name: str) -> None:
    conn = bootstrap()
    config = as_config(conn)
    conn.close()
    if not getattr(config.ai, token_field):
        logger.error("%s: ai.%s isn't set — nothing to do", command_name, token_field)
        raise typer.Exit(code=1)

    # Imported only after the token check passes — python-telegram-bot and
    # discord.py are heavy-ish deps not worth loading for a command that's
    # about to immediately exit.
    import importlib

    importlib.import_module(module_name).run(config.ai)


if __name__ == "__main__":
    app()

from __future__ import annotations

import dataclasses

from skytracer.config import build_config, validate
from skytracer.db import init_db
from skytracer.settings_store import (
    as_dict,
    backfill_missing,
    flatten,
    get,
    mask_secrets,
    seed_if_empty,
    set,
    unflatten,
)


def test_flatten_unflatten_round_trip() -> None:
    nested = {"a": {"b": 1, "c": "x"}, "d": True}
    flat = flatten(nested)
    assert flat == {"a.b": "1", "a.c": '"x"', "d": "true"}
    assert unflatten(flat) == nested


def test_seed_then_round_trip(tmp_path, valid_raw_config: dict) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    result = validate(valid_raw_config)

    seeded = seed_if_empty(conn, result.config)
    assert seeded is True

    restored = as_dict(conn)
    assert restored == dataclasses.asdict(result.config)


def test_seed_is_noop_when_not_empty(tmp_path, valid_raw_config: dict) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    result = validate(valid_raw_config)
    assert seed_if_empty(conn, result.config) is True

    set(conn, "trip.origin", "DFW")
    assert seed_if_empty(conn, result.config) is False
    assert get(conn, "trip.origin") == "DFW"


def test_get_set(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    assert get(conn, "trip.origin") is None
    assert get(conn, "trip.origin", "OKC") == "OKC"

    set(conn, "trip.origin", "OKC")
    assert get(conn, "trip.origin") == "OKC"

    set(conn, "trip.origin", "DFW")
    assert get(conn, "trip.origin") == "DFW"


def test_mask_secrets_hides_configured_values() -> None:
    d = {
        "sources": {"kiwi": {"enabled": True, "api_key": "super-secret"}},
        "web": {"admin_password": "hunter2"},
        "notify": {"whatsapp": {"phone": "+14055551234"}},
    }
    masked = mask_secrets(d)
    assert masked["sources"]["kiwi"]["api_key"] == "•••• set"
    assert masked["web"]["admin_password"] == "•••• set"
    # non-secret fields untouched
    assert masked["notify"]["whatsapp"]["phone"] == "+14055551234"
    assert masked["sources"]["kiwi"]["enabled"] is True


def test_mask_secrets_leaves_empty_secrets_empty() -> None:
    d = {"sources": {"kiwi": {"api_key": ""}}}
    masked = mask_secrets(d)
    assert masked["sources"]["kiwi"]["api_key"] == ""


def test_mask_secrets_does_not_mutate_input() -> None:
    d = {"web": {"admin_password": "hunter2"}}
    mask_secrets(d)
    assert d["web"]["admin_password"] == "hunter2"


def _seed_legacy_single_trip(conn) -> None:
    """Simulate a real pre-multi-trip settings table that has already been
    through every prior backfill generation (dashboard, ai.provider,
    ai.llamaserver_*, ai.searxng_base_url) but predates the trips migration
    specifically — the state a real, actively-maintained install would
    actually be in. Trip/alerts values are deliberately different from the
    shared fixture so a carry-over bug can't hide behind coincidentally-
    matching defaults.
    """
    legacy = {
        "trip.origin": "LAX",
        "trip.destination": "LHR",
        "trip.adults": 3,
        "trip.cabin": "premium_economy",
        "trip.currency": "GBP",
        "trip.fixed.enabled": False,
        "trip.fixed.depart_date": "",
        "trip.fixed.return_date": "",
        "trip.flexible.enabled": True,
        "trip.flexible.earliest_depart": "2026-08-01",
        "trip.flexible.latest_depart": "2026-08-20",
        "trip.flexible.trip_length_days": 14,
        "trip.flexible.scan_step_days": 7,
        "alerts.threshold_price": 1234.56,
        "alerts.drop_percent": 15,
        "alerts.notify_on_new_low": False,
        "alerts.cooldown_hours": 0,
        "schedule.every_hours": 6,
        "sources.google.enabled": True,
        "sources.google.use_browser_fallback": True,
        "sources.kiwi.enabled": False,
        "sources.kiwi.api_key": "",
        "sources.travelpayouts.enabled": False,
        "sources.travelpayouts.token": "",
        "sources.duffel.enabled": False,
        "sources.duffel.api_key": "",
        "sources.mcp.enabled": False,
        "sources.mcp.endpoint": "",
        "sources.mcp.tool_name": "search_flights",
        "notify.channel": "ntfy",
        "notify.whatsapp.provider": "callmebot",
        "notify.whatsapp.phone": "",
        "notify.whatsapp.callmebot_apikey": "",
        "notify.whatsapp.cloud_api_phone_number_id": "",
        "notify.whatsapp.cloud_api_access_token": "",
        "notify.whatsapp.cloud_api_template_name": "",
        "notify.whatsapp.twilio_account_sid": "",
        "notify.whatsapp.twilio_auth_token": "",
        "notify.whatsapp.twilio_from_number": "",
        "notify.ntfy.server": "https://ntfy.sh",
        "notify.ntfy.topic": "legacy-topic",
        "notify.discord.webhook_url": "",
        "notify.email.smtp_host": "",
        "notify.email.smtp_port": 587,
        "notify.email.username": "",
        "notify.email.password": "",
        "notify.email.to_addr": "",
        "dashboard.top_n_fares": 5,
        "ai.provider": "ollama",
        "ai.ollama_base_url": "http://localhost:11434/v1",
        "ai.ollama_model": "llama3",
        "ai.llamaserver_base_url": "http://localhost:11435/v1",
        "ai.llamaserver_model": "",
        "ai.enable_thinking": False,
        "ai.searxng_base_url": "",
        "ai.anthropic_api_key": "",
        "ai.telegram_bot_token": "",
        "ai.telegram_allowed_user_id": "",
        "ai.discord_bot_token": "",
        "ai.discord_allowed_user_id": "",
        "web.host": "0.0.0.0",
        "web.port": 8087,
        "web.admin_password": "hashed-not-relevant-here",
        "db.path": "/var/lib/skytracer/skytracer.db",
    }
    for key, value in legacy.items():
        set(conn, key, value)


def test_backfill_migrates_legacy_single_trip_to_trips_list(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    _seed_legacy_single_trip(conn)

    assert get(conn, "trips", None) is None  # sanity: genuinely pre-migration

    backfill_missing(conn)

    trips = get(conn, "trips")
    assert trips == [
        {
            "trip": {
                "origin": "LAX",
                "destination": "LHR",
                "adults": 3,
                "cabin": "premium_economy",
                "currency": "GBP",
                "fixed": {"enabled": False, "depart_date": "", "return_date": ""},
                "flexible": {
                    "enabled": True,
                    "earliest_depart": "2026-08-01",
                    "latest_depart": "2026-08-20",
                    "trip_length_days": 14,
                    "scan_step_days": 7,
                },
            },
            "alerts": {
                "threshold_price": 1234.56,
                "drop_percent": 15,
                "notify_on_new_low": False,
                "cooldown_hours": 0,
            },
        }
    ]
    # Legacy keys are left in place, not deleted (settings DB only ever adds).
    assert get(conn, "trip.origin") == "LAX"
    assert get(conn, "alerts.threshold_price") == 1234.56


def test_backfill_is_idempotent_and_does_not_overwrite_migrated_trips(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    _seed_legacy_single_trip(conn)
    backfill_missing(conn)
    first_pass = get(conn, "trips")

    backfill_missing(conn)
    assert get(conn, "trips") == first_pass


def test_backfill_does_not_resurrect_a_deliberately_emptied_trips_list(tmp_path) -> None:
    """A present-but-empty `trips` list means the user removed every tracked
    trip via the Settings page — backfill must leave that alone, not treat
    an empty list the same as a missing key.
    """
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    _seed_legacy_single_trip(conn)
    set(conn, "trips", [])

    backfill_missing(conn)

    assert get(conn, "trips") == []


def test_migrated_settings_build_a_valid_config(tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    conn = init_db(db_path)
    _seed_legacy_single_trip(conn)
    backfill_missing(conn)

    config = build_config(as_dict(conn))
    assert len(config.trips) == 1
    assert config.trips[0].trip.origin == "LAX"
    assert config.trips[0].alerts.threshold_price == 1234.56

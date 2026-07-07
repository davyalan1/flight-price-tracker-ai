"""Runtime settings store: the SQLite `settings` table is the source of truth.

config.toml only seeds this table once, on first boot (when it's empty). The
web Settings page (Phase 5) and the poller both read/write through here, not
the TOML file — this avoids file-write races between the web UI and the
systemd-triggered poll.

Values are stored as one JSON-encoded string per dotted key, e.g.
`trip.origin` -> `"OKC"`, `sources.kiwi.enabled` -> `false`. This lets
individual fields be updated without a read-modify-write of one giant blob.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import sqlite3
from typing import Any

from skytracer.config import Config, build_config

SECRET_KEYS = {
    "sources.kiwi.api_key",
    "sources.travelpayouts.token",
    "sources.duffel.api_key",
    "notify.whatsapp.callmebot_apikey",
    "notify.discord.webhook_url",
    "notify.email.password",
    "ai.anthropic_api_key",
    "ai.telegram_bot_token",
    "ai.discord_bot_token",
    "web.admin_password",
}


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, full_key))
        else:
            out[full_key] = json.dumps(value)
    return out


def unflatten(rows: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted_key, raw_value in rows.items():
        value = json.loads(raw_value)
        parts = dotted_key.split(".")
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return out


def seed_if_empty(conn: sqlite3.Connection, config: Config) -> bool:
    """Seed the settings table from `config` if it's currently empty.

    Returns True if seeding happened, False if the table already had data
    (in which case it is left untouched).
    """
    (count,) = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
    if count > 0:
        return False
    flat = flatten(dataclasses.asdict(config))
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)",
        list(flat.items()),
    )
    conn.commit()
    return True


def get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row[0])


def set(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


def backfill_missing(conn: sqlite3.Connection) -> None:
    """Add settings keys introduced after a DB was already seeded, so an
    existing live install doesn't KeyError building Config from a dict
    that predates the new field. Extend this as new top-level sections
    get added post-launch.
    """
    if get(conn, "dashboard.top_n_fares", None) is None:
        set(conn, "dashboard.top_n_fares", 5)
    if get(conn, "ai.provider", None) is None:
        set(conn, "ai.provider", "ollama")
        set(conn, "ai.ollama_base_url", "http://localhost:11434/v1")
        set(conn, "ai.ollama_model", "llama3")
        set(conn, "ai.anthropic_api_key", "")
        set(conn, "ai.telegram_bot_token", "")
        set(conn, "ai.telegram_allowed_user_id", "")
        set(conn, "ai.discord_bot_token", "")
        set(conn, "ai.discord_allowed_user_id", "")
    # Added after ai.provider itself — a settings table seeded between that
    # first ai.* rollout and this one would have ai.provider set but not
    # these, so they need their own independent check.
    if get(conn, "ai.llamaserver_base_url", None) is None:
        set(conn, "ai.llamaserver_base_url", "http://localhost:11435/v1")
        set(conn, "ai.llamaserver_model", "")
        set(conn, "ai.enable_thinking", False)
    # Added after the llamaserver rollout — same reasoning as above.
    if get(conn, "ai.searxng_base_url", None) is None:
        set(conn, "ai.searxng_base_url", "")
    # Multi-trip tracking replaced the single top-level `trip`/`alerts` keys
    # with a `trips` list — any install seeded before that change still has
    # the old flat keys and no `trips` key at all. Wrap them into a
    # single-entry list so the existing trip/alerts carry over exactly, with
    # zero data loss. An install already migrated (including one where every
    # trip has since been removed via the Settings page, leaving
    # `trips == []`) must NOT be re-migrated — checking for the key's mere
    # presence, not its content, is what makes that safe.
    if get(conn, "trips", None) is None:
        all_rows = dict(conn.execute("SELECT key, value FROM settings"))
        legacy_trip = unflatten(
            {k: v for k, v in all_rows.items() if k.startswith("trip.")}
        ).get("trip")
        legacy_alerts = unflatten(
            {k: v for k, v in all_rows.items() if k.startswith("alerts.")}
        ).get("alerts")
        if legacy_trip is not None and legacy_alerts is not None:
            set(conn, "trips", [{"trip": legacy_trip, "alerts": legacy_alerts}])
        else:
            set(conn, "trips", [])


def as_dict(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = {key: value for key, value in conn.execute("SELECT key, value FROM settings")}
    return unflatten(rows)


def as_config(conn: sqlite3.Connection) -> Config:
    """The current settings, typed. Convenience wrapper around
    build_config(as_dict(conn)) for callers (poller, CLI, web) that want
    attribute access instead of a nested dict.
    """
    return build_config(as_dict(conn))


def save_config(conn: sqlite3.Connection, config: Config) -> None:
    """Persist a full validated Config back to the settings table.

    Used by the Settings page after a successful save. Only upserts the
    keys that belong to Config — internal.* operational state (watchdog
    counter, session secret) isn't part of Config and is left untouched.
    """
    flat = flatten(dataclasses.asdict(config))
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        list(flat.items()),
    )
    conn.commit()


def mask_secrets(d: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of a nested settings dict with secret fields masked."""
    masked = copy.deepcopy(d)
    for dotted_key in SECRET_KEYS:
        parts = dotted_key.split(".")
        node = masked
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if not isinstance(node, dict):
            continue
        leaf = parts[-1]
        if leaf in node:
            node[leaf] = "•••• set" if node[leaf] else ""
    return masked

"""Shared "make sure settings exist" logic for the CLI and the web app: seed
the settings table from config.toml exactly once, the first time it's empty.
"""

from __future__ import annotations

import logging
import sqlite3

from skytracer.config import ConfigError, load_and_validate
from skytracer.paths import resolve_config_path
from skytracer.settings_store import backfill_missing, seed_if_empty

logger = logging.getLogger("skytracer.bootstrap")


class BootstrapError(Exception):
    """Raised when the initial config.toml seed is missing or invalid."""


def ensure_seeded(conn: sqlite3.Connection) -> None:
    (count,) = conn.execute("SELECT COUNT(*) FROM settings").fetchone()
    if count > 0:
        backfill_missing(conn)
        return

    config_path = resolve_config_path()
    try:
        result = load_and_validate(config_path)
    except ConfigError as exc:
        for message in exc.messages:
            logger.error("config error: %s", message)
        raise BootstrapError(f"invalid seed config at {config_path}") from exc
    except FileNotFoundError as exc:
        logger.error("config file not found: %s", config_path)
        raise BootstrapError(f"config file not found: {config_path}") from exc

    for warning in result.warnings:
        logger.warning(warning)
    seed_if_empty(conn, result.config)
    logger.info("seeded settings from %s", config_path)

"""Where the CLI and web app find the config seed and the database.

Both default to the real install locations (Phase 9's bootstrap.sh sets
these up); env vars override them for local development.
"""

from __future__ import annotations

import os

DEFAULT_CONFIG_PATH = "/etc/skytracer/config.toml"
DEFAULT_DB_PATH = "/var/lib/skytracer/skytracer.db"


def resolve_config_path() -> str:
    return os.environ.get("SKYTRACER_CONFIG", DEFAULT_CONFIG_PATH)


def resolve_db_path() -> str:
    return os.environ.get("SKYTRACER_DB", DEFAULT_DB_PATH)

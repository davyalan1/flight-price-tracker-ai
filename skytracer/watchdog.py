"""Consecutive-failure tracking (spec constraint #5: fail loud, not silent —
after N consecutive poll failures, something should tell the operator the
tracker itself is broken, not just that one poll came back empty).

The counter is persisted under an `internal.*` settings key rather than a
new table: it's operational state, not user config, so the Settings page
(Phase 5) should never render or accept edits to `internal.*` keys.
"""

from __future__ import annotations

import sqlite3

from skytracer import settings_store

CONSECUTIVE_FAILURES_KEY = "internal.consecutive_poll_failures"
CONSECUTIVE_FAILURE_THRESHOLD = 3


def record_failure(conn: sqlite3.Connection) -> int:
    count = settings_store.get(conn, CONSECUTIVE_FAILURES_KEY, 0) + 1
    settings_store.set(conn, CONSECUTIVE_FAILURES_KEY, count)
    return count


def record_success(conn: sqlite3.Connection) -> None:
    settings_store.set(conn, CONSECUTIVE_FAILURES_KEY, 0)


def is_broken(consecutive_failures: int, threshold: int = CONSECUTIVE_FAILURE_THRESHOLD) -> bool:
    return consecutive_failures >= threshold

"""Pure, platform-independent reply builders for the /status and /lowest
bot commands — templated (not LLM-generated) so these two common questions
always get a reliable, exact answer. Anything else falls through to
ai.answer.answer_question (LLM, grounded in the same underlying data).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from skytracer import stats as stats_module
from skytracer.observations import fetch_price_points, list_route_keys
from skytracer.stats import RouteStats

_NO_DATA = "No tracked routes have any data yet — the first poll hasn't run."


def _per_route_reply(conn: sqlite3.Connection, line: Callable[[str, RouteStats], str]) -> str:
    route_keys = list_route_keys(conn)
    if not route_keys:
        return _NO_DATA

    lines = []
    for route_key in route_keys:
        route_stats = stats_module.compute_stats(route_key, fetch_price_points(conn, route_key))
        if route_stats is not None:
            lines.append(line(route_key, route_stats))
    return "\n".join(lines) if lines else _NO_DATA


def status_reply(conn: sqlite3.Connection) -> str:
    def line(route_key: str, s: RouteStats) -> str:
        arrow = {"down": "↓", "up": "↑", "flat": "→"}[s.trend]
        return f"{route_key}: {s.current_price:.2f} {arrow} {s.trend}"

    return _per_route_reply(conn, line)


def lowest_reply(conn: sqlite3.Connection) -> str:
    def line(route_key: str, s: RouteStats) -> str:
        return f"{route_key}: all-time low {s.all_time_low:.2f}"

    return _per_route_reply(conn, line)

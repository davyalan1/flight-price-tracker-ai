"""Builds a compact, plain-text summary of real tracked-route data to inject
into the LLM's system prompt — prompt-grounding rather than tool-calling
(see PHASE11_CONVERSATIONAL_AI_RESEARCH.md for why: this app's question
domain is small and fixed, and small local models are unreliable at
deciding when/how to call a tool).
"""

from __future__ import annotations

import sqlite3

from skytracer import stats as stats_module
from skytracer.alerts import fetch_alert_history
from skytracer.observations import fetch_price_points, list_route_keys


def build_grounding_context(conn: sqlite3.Connection) -> str:
    route_keys = list_route_keys(conn)
    if not route_keys:
        return "No tracked routes have any data yet — no polls have completed."

    blocks = []
    for route_key in route_keys:
        points = fetch_price_points(conn, route_key)
        route_stats = stats_module.compute_stats(route_key, points)
        if route_stats is None:
            continue
        lines = [
            f"Route: {route_key}",
            f"  Current price: {route_stats.current_price:.2f} "
            f"(as of {route_stats.current_observed_at})",
            f"  All-time low: {route_stats.all_time_low:.2f}",
            f"  All-time high: {route_stats.all_time_high:.2f}",
            f"  30-day low: {route_stats.low_30d:.2f}",
            f"  Trend: {route_stats.trend}",
        ]
        alerts = fetch_alert_history(conn, route_key, limit=5)
        if alerts:
            lines.append("  Recent alerts:")
            for a in alerts:
                lines.append(f"    - {a['sent_at']}: {a['reason']}, price {a['price']:.2f}")
        else:
            lines.append("  Recent alerts: none")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)

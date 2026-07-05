"""Inline SVG price-history chart. The build spec allows Chart.js from a CDN
or inline SVG; inline SVG is chosen so the Dashboard keeps working with no
network access (a system already designed to work standalone with no LLM
and no required external JS). Pure function: points in, markup string (or
None when there isn't enough data to draw a line) out — no DB or request
context needed, so it's unit-testable with plain seeded data.
"""

from __future__ import annotations

from datetime import datetime

from skytracer.models import PricePoint

WIDTH = 600
HEIGHT = 180
PADDING = 24


def render_price_history_svg(points: list[PricePoint]) -> str | None:
    if len(points) < 2:
        return None

    sorted_points = sorted(points, key=lambda p: p.observed_at)
    times = [datetime.fromisoformat(p.observed_at).timestamp() for p in sorted_points]
    prices = [p.price for p in sorted_points]

    t_min, t_max = min(times), max(times)
    p_min, p_max = min(prices), max(prices)
    t_span = t_max - t_min or 1.0
    p_span = p_max - p_min or 1.0

    def to_x(t: float) -> float:
        return PADDING + (t - t_min) / t_span * (WIDTH - 2 * PADDING)

    def to_y(price: float) -> float:
        # A higher price should sit higher on the page (smaller SVG y).
        return HEIGHT - PADDING - (price - p_min) / p_span * (HEIGHT - 2 * PADDING)

    coords = [(to_x(t), to_y(price)) for t, price in zip(times, prices, strict=True)]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="chart-dot" />' for x, y in coords
    )

    return (
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="price-chart" role="img" '
        f'aria-label="Price history from {prices[0]:.0f} to {prices[-1]:.0f}">'
        f'<polyline points="{polyline}" class="chart-line" fill="none" />'
        f"{dots}"
        f"</svg>"
    )

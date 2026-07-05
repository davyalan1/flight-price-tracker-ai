"""Route price statistics. Pure functions over a list of PricePoints — no DB
access here, so this is unit-testable with plain seeded data (see
observations.fetch_price_points for how points are read from SQLite).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from skytracer.models import PricePoint

THIRTY_DAYS = timedelta(days=30)


@dataclass
class RouteStats:
    route_key: str
    current_price: float
    current_observed_at: str
    all_time_low: float
    all_time_high: float
    low_30d: float
    trend: str  # "up" | "down" | "flat"


def compute_stats(
    route_key: str, points: list[PricePoint], now: datetime | None = None
) -> RouteStats | None:
    if not points:
        return None

    sorted_points = sorted(points, key=lambda p: p.observed_at)
    current = sorted_points[-1]
    prices = [p.price for p in sorted_points]

    cutoff = (now or datetime.now(UTC)) - THIRTY_DAYS
    recent_prices = [
        p.price for p in sorted_points if datetime.fromisoformat(p.observed_at) >= cutoff
    ]

    previous = sorted_points[-2] if len(sorted_points) >= 2 else None
    if previous is None or current.price == previous.price:
        trend = "flat"
    elif current.price < previous.price:
        trend = "down"
    else:
        trend = "up"

    return RouteStats(
        route_key=route_key,
        current_price=current.price,
        current_observed_at=current.observed_at,
        all_time_low=min(prices),
        all_time_high=max(prices),
        low_30d=min(recent_prices) if recent_prices else current.price,
        trend=trend,
    )

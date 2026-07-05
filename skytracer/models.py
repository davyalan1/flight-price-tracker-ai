"""Core data types shared across fare sources, storage, and stats."""

from __future__ import annotations

from dataclasses import dataclass

from skytracer.config import TripConfig


@dataclass
class SearchQuery:
    origin: str
    destination: str
    depart_date: str
    return_date: str | None
    adults: int
    cabin: str
    currency: str


@dataclass
class FareResult:
    price: float
    currency: str
    airlines: list[str]
    stops: int
    duration_min: int | None
    route: str
    source: str
    deep_link: str | None = None
    raw: dict | None = None


@dataclass
class Alert:
    """What a Notifier renders and sends — one per triggered-reasons batch,
    not one per reason (a single price drop can trigger several reasons at
    once and should read as one message, not a flood of them).
    """

    route_key: str
    route: str
    price: float
    currency: str
    reasons: list[str]
    all_time_low: float
    deep_link: str | None
    dashboard_url: str | None


@dataclass(frozen=True)
class PricePoint:
    """A minimal (observed_at, price) pair — the only shape stats.py and
    alerts.py need, so both stay pure and testable without a DB.
    """

    observed_at: str
    price: float


def route_key_for_trip(trip: TripConfig) -> str:
    """Stable identity for "the itinerary being tracked", independent of which
    exact date within a flexible window gets sampled on any given poll — this
    is what groups observations together for stats/dashboard purposes.
    """
    if trip.fixed.enabled:
        dates = f"{trip.fixed.depart_date}_{trip.fixed.return_date or 'oneway'}"
    else:
        dates = (
            f"{trip.flexible.earliest_depart}_{trip.flexible.latest_depart}"
            f"_{trip.flexible.trip_length_days}d"
        )
    return f"{trip.origin}-{trip.destination}-{trip.cabin}-{dates}"

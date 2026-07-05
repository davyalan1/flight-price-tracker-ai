from __future__ import annotations

from datetime import UTC, datetime

from skytracer.models import PricePoint
from skytracer.stats import compute_stats


def test_compute_stats_none_when_no_points() -> None:
    assert compute_stats("route", []) is None


def test_compute_stats_single_point() -> None:
    points = [PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=1000.0)]
    stats = compute_stats("route", points)
    assert stats.current_price == 1000.0
    assert stats.all_time_low == 1000.0
    assert stats.all_time_high == 1000.0
    assert stats.low_30d == 1000.0
    assert stats.trend == "flat"


def test_compute_stats_all_time_low_and_high() -> None:
    points = [
        PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=1000.0),
        PricePoint(observed_at="2026-06-02T00:00:00+00:00", price=800.0),
        PricePoint(observed_at="2026-06-03T00:00:00+00:00", price=1200.0),
    ]
    stats = compute_stats("route", points)
    assert stats.all_time_low == 800.0
    assert stats.all_time_high == 1200.0
    assert stats.current_price == 1200.0


def test_compute_stats_trend_down_and_up() -> None:
    down_points = [
        PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=1000.0),
        PricePoint(observed_at="2026-06-02T00:00:00+00:00", price=900.0),
    ]
    assert compute_stats("route", down_points).trend == "down"

    up_points = [
        PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=900.0),
        PricePoint(observed_at="2026-06-02T00:00:00+00:00", price=1000.0),
    ]
    assert compute_stats("route", up_points).trend == "up"

    flat_points = [
        PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=900.0),
        PricePoint(observed_at="2026-06-02T00:00:00+00:00", price=900.0),
    ]
    assert compute_stats("route", flat_points).trend == "flat"


def test_compute_stats_ignores_point_order() -> None:
    points = [
        PricePoint(observed_at="2026-06-03T00:00:00+00:00", price=1200.0),
        PricePoint(observed_at="2026-06-01T00:00:00+00:00", price=1000.0),
        PricePoint(observed_at="2026-06-02T00:00:00+00:00", price=800.0),
    ]
    stats = compute_stats("route", points)
    # current should be the *latest by time*, not the last in the input list
    assert stats.current_price == 1200.0
    assert stats.current_observed_at == "2026-06-03T00:00:00+00:00"


def test_compute_stats_30_day_low_excludes_older_points() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    points = [
        PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=500.0),  # >30d old, excluded
        PricePoint(observed_at="2026-06-15T00:00:00+00:00", price=900.0),
        PricePoint(observed_at="2026-06-30T00:00:00+00:00", price=950.0),
    ]
    stats = compute_stats("route", points, now=now)
    assert stats.all_time_low == 500.0  # all-time still sees the old point
    assert stats.low_30d == 900.0  # 30-day low does not

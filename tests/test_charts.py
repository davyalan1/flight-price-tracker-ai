from __future__ import annotations

from skytracer.charts import render_price_history_svg
from skytracer.models import PricePoint


def test_render_returns_none_for_fewer_than_two_points() -> None:
    assert render_price_history_svg([]) is None
    assert (
        render_price_history_svg(
            [PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=100.0)]
        )
        is None
    )


def test_render_produces_svg_with_one_point_per_observation() -> None:
    points = [
        PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=1500.0),
        PricePoint(observed_at="2026-01-02T00:00:00+00:00", price=1200.0),
        PricePoint(observed_at="2026-01-03T00:00:00+00:00", price=1300.0),
    ]
    svg = render_price_history_svg(points)
    assert svg is not None
    assert svg.startswith("<svg")
    assert svg.count("<circle") == 3
    assert "polyline" in svg


def test_render_handles_unsorted_input() -> None:
    points = [
        PricePoint(observed_at="2026-01-03T00:00:00+00:00", price=1300.0),
        PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=1500.0),
        PricePoint(observed_at="2026-01-02T00:00:00+00:00", price=1200.0),
    ]
    svg = render_price_history_svg(points)
    assert svg is not None
    # aria-label reports earliest -> latest by time, after sorting by observed_at.
    assert 'aria-label="Price history from 1500 to 1300"' in svg


def test_render_handles_flat_price_series_without_div_by_zero() -> None:
    points = [
        PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=1000.0),
        PricePoint(observed_at="2026-01-01T00:00:00+00:00", price=1000.0),
    ]
    svg = render_price_history_svg(points)
    assert svg is not None

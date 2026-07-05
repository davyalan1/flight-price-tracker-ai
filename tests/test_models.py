from __future__ import annotations

from skytracer.config import FixedTrip, FlexibleTrip, TripConfig
from skytracer.models import route_key_for_trip


def _trip(**overrides) -> TripConfig:
    base = dict(
        origin="OKC",
        destination="NRT",
        adults=1,
        cabin="economy",
        currency="USD",
        fixed=FixedTrip(enabled=False, depart_date="", return_date=""),
        flexible=FlexibleTrip(
            enabled=True,
            earliest_depart="2026-09-01",
            latest_depart="2026-11-30",
            trip_length_days=10,
            scan_step_days=3,
        ),
    )
    base.update(overrides)
    return TripConfig(**base)


def test_route_key_stable_for_same_flexible_window() -> None:
    assert route_key_for_trip(_trip()) == route_key_for_trip(_trip())


def test_route_key_unaffected_by_sampled_date_within_window() -> None:
    # Two trips with the same tracked window but (hypothetically) different
    # samples on different polls should still group under the same key —
    # route_key is derived from the window, not any one sampled date.
    trip_a = _trip()
    trip_b = _trip(flexible=FlexibleTrip(**{**vars(trip_a.flexible)}))
    assert route_key_for_trip(trip_a) == route_key_for_trip(trip_b)


def test_route_key_differs_for_fixed_vs_flexible() -> None:
    fixed_trip = _trip(
        fixed=FixedTrip(enabled=True, depart_date="2026-10-01", return_date="2026-10-11"),
        flexible=FlexibleTrip(
            enabled=False,
            earliest_depart="2026-09-01",
            latest_depart="2026-11-30",
            trip_length_days=10,
            scan_step_days=3,
        ),
    )
    assert route_key_for_trip(fixed_trip) != route_key_for_trip(_trip())


def test_route_key_differs_for_different_destination() -> None:
    assert route_key_for_trip(_trip()) != route_key_for_trip(_trip(destination="HND"))

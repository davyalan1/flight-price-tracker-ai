from __future__ import annotations

from skytracer.db import init_db
from skytracer.models import FareResult, SearchQuery
from skytracer.observations import (
    fetch_observations,
    fetch_price_points,
    fetch_top_n_for_latest_poll,
    insert_observation,
)


def test_insert_observation_round_trip(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-09-01",
        return_date="2026-09-11",
        adults=1,
        cabin="economy",
        currency="USD",
    )
    result = FareResult(
        price=987.65,
        currency="USD",
        airlines=["United", "ANA"],
        stops=2,
        duration_min=845,
        route="OKC → DEN → NRT",
        source="google",
        deep_link="https://www.google.com/travel/flights/search?tfs=abc",
    )
    insert_observation(conn, route_key="OKC-NRT-economy-test", query=query, result=result)

    row = conn.execute("SELECT * FROM observations").fetchone()
    assert row["route_key"] == "OKC-NRT-economy-test"
    assert row["origin"] == "OKC"
    assert row["destination"] == "NRT"
    assert row["depart_date"] == "2026-09-01"
    assert row["return_date"] == "2026-09-11"
    assert row["price"] == 987.65
    assert row["currency"] == "USD"
    assert row["stops"] == 2
    assert row["route"] == "OKC → DEN → NRT"
    assert row["source"] == "google"
    assert row["deep_link"].startswith("https://")
    assert row["observed_at"]  # non-empty, ISO8601 UTC timestamp


def test_insert_observation_defaults_observed_at_to_now(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-09-01",
        return_date=None,
        adults=1,
        cabin="economy",
        currency="USD",
    )
    result = FareResult(
        price=500.0,
        currency="USD",
        airlines=["United"],
        stops=1,
        duration_min=600,
        route="OKC → DEN → NRT",
        source="google",
    )
    insert_observation(conn, route_key="k", query=query, result=result)
    row = conn.execute("SELECT observed_at, return_date FROM observations").fetchone()
    assert row["observed_at"].endswith("+00:00") or "Z" in row["observed_at"]
    assert row["return_date"] is None


def _query() -> SearchQuery:
    return SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-09-01",
        return_date="2026-09-11",
        adults=1,
        cabin="economy",
        currency="USD",
    )


def _fare(price: float) -> FareResult:
    return FareResult(
        price=price,
        currency="USD",
        airlines=["United"],
        stops=1,
        duration_min=600,
        route="OKC → DEN → NRT",
        source="google",
    )


def test_top_n_fares_share_one_observed_at_and_are_excluded_from_price_points(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    observed_at = "2026-01-01T00:00:00+00:00"
    for rank, price in enumerate([500.0, 550.0, 600.0]):
        insert_observation(
            conn,
            route_key="k",
            query=_query(),
            result=_fare(price),
            observed_at=observed_at,
            rank=rank,
        )

    # Only the rank=0 winner counts as "the" observation for this poll —
    # stats/alerts/chart history must not see the 2nd/3rd cheapest as if
    # they were separate polls.
    points = fetch_price_points(conn, "k")
    assert [p.price for p in points] == [500.0]

    top = fetch_top_n_for_latest_poll(conn, "k", 3)
    assert [row["price"] for row in top] == [500.0, 550.0, 600.0]

    history = fetch_observations(conn, "k")
    assert len(history) == 1
    assert history[0]["price"] == 500.0


def test_top_n_for_latest_poll_only_returns_latest_poll(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    insert_observation(
        conn, route_key="k", query=_query(), result=_fare(900.0),
        observed_at="2026-01-01T00:00:00+00:00", rank=0,
    )
    insert_observation(
        conn, route_key="k", query=_query(), result=_fare(500.0),
        observed_at="2026-01-02T00:00:00+00:00", rank=0,
    )
    insert_observation(
        conn, route_key="k", query=_query(), result=_fare(520.0),
        observed_at="2026-01-02T00:00:00+00:00", rank=1,
    )

    top = fetch_top_n_for_latest_poll(conn, "k", 5)
    assert [row["price"] for row in top] == [500.0, 520.0]

from __future__ import annotations

from skytracer.db import init_db
from skytracer.models import FareResult, SearchQuery
from skytracer.observations import insert_observation

ROUTE_KEY = "OKC-NRT-economy-2026-12-14_2027-01-08"


def _insert_observation(db_path, price: float, observed_at: str) -> None:
    conn = init_db(db_path)
    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-12-14",
        return_date="2027-01-08",
        adults=1,
        cabin="economy",
        currency="USD",
    )
    result = FareResult(
        price=price,
        currency="USD",
        airlines=["ANA"],
        stops=1,
        duration_min=600,
        route="OKC → NRT",
        source="google",
        deep_link="https://example.com",
    )
    insert_observation(
        conn, route_key=ROUTE_KEY, query=query, result=result, observed_at=observed_at
    )
    conn.close()


def test_dashboard_last_updated_is_marked_for_client_side_local_time(
    web_client, tmp_path
) -> None:
    db_path = tmp_path / "skytracer.db"
    _insert_observation(db_path, 1500.0, "2026-01-01T00:18:34+00:00")

    response = web_client.get("/")
    assert 'class="local-time" data-iso="2026-01-01T00:18:34+00:00"' in response.text


def test_route_detail_renders_chart_with_enough_observations(web_client, tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    _insert_observation(db_path, 1500.0, "2026-01-01T00:00:00+00:00")
    _insert_observation(db_path, 1200.0, "2026-01-02T00:00:00+00:00")

    response = web_client.get(f"/route/{ROUTE_KEY}")
    assert response.status_code == 200
    assert "<svg" in response.text
    assert "price-chart" in response.text


def test_route_detail_shows_hint_when_not_enough_observations(web_client) -> None:
    response = web_client.get(f"/route/{ROUTE_KEY}")
    assert response.status_code == 200
    assert "Not enough observations yet" in response.text
    assert "<svg" not in response.text


def test_route_detail_shows_top_fares_and_route_map(web_client, tmp_path) -> None:
    db_path = tmp_path / "skytracer.db"
    _insert_observation(db_path, 1500.0, "2026-01-01T00:00:00+00:00")

    response = web_client.get(f"/route/{ROUTE_KEY}")
    assert response.status_code == 200
    assert "Best fares right now" in response.text
    assert "1500.00" in response.text
    assert "route-map" in response.text  # OKC/NRT are both in the vendored table
    assert "No alerts sent for this route yet" in response.text


def test_route_detail_observed_at_is_marked_for_client_side_local_time(
    web_client, tmp_path
) -> None:
    db_path = tmp_path / "skytracer.db"
    _insert_observation(db_path, 1500.0, "2026-01-01T00:18:34+00:00")

    response = web_client.get(f"/route/{ROUTE_KEY}")
    # The raw UTC timestamp is rendered inside a data-iso attribute so
    # base.html's shared JS can convert it to the visitor's local time —
    # asserting the markup here, since a browser is what actually runs it.
    assert 'class="local-time" data-iso="2026-01-01T00:18:34+00:00"' in response.text
    assert "Observed</th>" in response.text  # no longer hardcoded "(UTC)"

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fast_flights.querying import Trip

from skytracer.models import SearchQuery
from skytracer.sources import google as google_module
from skytracer.sources.google import GoogleFlightsSource


def _fake_flight(price: float, airports: list[str], airlines: list[str], durations: list[int]):
    segments = []
    for i in range(len(airports) - 1):
        segments.append(
            SimpleNamespace(
                from_airport=SimpleNamespace(code=airports[i]),
                to_airport=SimpleNamespace(code=airports[i + 1]),
                duration=durations[i],
            )
        )
    return SimpleNamespace(price=price, airlines=airlines, flights=segments)


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-09-01",
        return_date="2026-09-11",
        adults=1,
        cabin="economy",
        currency="USD",
    )


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(google_module.time, "sleep", lambda _seconds: None)


def test_search_normalizes_cheapest_and_stops(monkeypatch, query: SearchQuery) -> None:
    fakes = [
        _fake_flight(
            1579.0, ["OKC", "DEN", "YVR", "NRT"], ["United", "Air Canada"], [116, 180, 585]
        ),
        _fake_flight(1693.0, ["OKC", "PHX", "NRT"], ["American"], [151, 900]),
    ]
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: fakes)

    source = GoogleFlightsSource(enabled=True, use_browser_fallback=True)
    results = source.search(query)

    assert len(results) == 2
    cheapest = min(results, key=lambda f: f.price)
    assert cheapest.price == 1579.0
    assert cheapest.stops == 2
    assert cheapest.route == "OKC → DEN → YVR → NRT"
    assert cheapest.airlines == ["United", "Air Canada"]
    assert cheapest.source == "google"
    assert cheapest.currency == "USD"
    assert cheapest.deep_link and cheapest.deep_link.startswith("https://")
    assert cheapest.duration_min == 116 + 180 + 585


def test_search_retries_on_empty_then_succeeds(monkeypatch, query: SearchQuery) -> None:
    fake = _fake_flight(999.0, ["OKC", "DEN", "NRT"], ["United"], [100, 700])
    calls = {"n": 0}

    def flaky_get_flights(q):
        calls["n"] += 1
        return [] if calls["n"] < 3 else [fake]

    monkeypatch.setattr(google_module.ff, "get_flights", flaky_get_flights)

    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    results = source.search(query)

    assert calls["n"] == 3
    assert len(results) == 1
    assert results[0].price == 999.0


def test_search_raises_after_exhausting_retries_on_exceptions(
    monkeypatch, query: SearchQuery
) -> None:
    def always_fails(q):
        raise RuntimeError("network is down")

    monkeypatch.setattr(google_module.ff, "get_flights", always_fails)

    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    with pytest.raises(RuntimeError, match="network is down"):
        source.search(query)


def test_browser_fallback_used_when_rpc_empty_and_enabled(monkeypatch, query: SearchQuery) -> None:
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: [])
    fallback_fake = _fake_flight(2200.0, ["OKC", "NRT"], ["JAL"], [1200])
    source = GoogleFlightsSource(enabled=True, use_browser_fallback=True)
    monkeypatch.setattr(source, "_browser_fallback", lambda q: [fallback_fake])

    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 2200.0


def test_browser_fallback_skipped_when_disabled(monkeypatch, query: SearchQuery) -> None:
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: [])
    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)

    called = {"hit": False}

    def spy(q):
        called["hit"] = True
        return None

    monkeypatch.setattr(source, "_browser_fallback", spy)
    results = source.search(query)

    assert results == []
    assert called["hit"] is False


def test_health_check_true_when_results(monkeypatch) -> None:
    fake = _fake_flight(300.0, ["JFK", "LAX"], ["Delta"], [330])
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: [fake])
    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    assert source.health_check() is True


def test_health_check_false_on_exception(monkeypatch) -> None:
    def always_fails(q):
        raise RuntimeError("boom")

    monkeypatch.setattr(google_module.ff, "get_flights", always_fails)
    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    assert source.health_check() is False


def test_one_way_query_when_no_return_date(monkeypatch) -> None:
    one_way_query = SearchQuery(
        origin="OKC",
        destination="DEN",
        depart_date="2026-09-01",
        return_date=None,
        adults=1,
        cabin="economy",
        currency="USD",
    )
    captured = {}

    def capture_get_flights(q):
        captured["query"] = q
        return [_fake_flight(150.0, ["OKC", "DEN"], ["United"], [100])]

    monkeypatch.setattr(google_module.ff, "get_flights", capture_get_flights)
    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    results = source.search(one_way_query)

    assert len(results) == 1
    assert captured["query"].trip == Trip.ONE_WAY


def test_search_skips_non_positive_price_fares(monkeypatch, query: SearchQuery) -> None:
    fakes = [
        _fake_flight(0.0, ["OKC", "NRT"], ["Glitch"], [700]),
        _fake_flight(-5.0, ["OKC", "NRT"], ["Glitch"], [700]),
        _fake_flight(1200.0, ["OKC", "DEN", "NRT"], ["United"], [100, 700]),
    ]
    monkeypatch.setattr(google_module.ff, "get_flights", lambda q: fakes)

    source = GoogleFlightsSource(enabled=True, use_browser_fallback=False)
    results = source.search(query)

    assert len(results) == 1
    assert results[0].price == 1200.0

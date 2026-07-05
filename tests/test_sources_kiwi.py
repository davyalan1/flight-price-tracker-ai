from __future__ import annotations

import pytest

from skytracer.models import SearchQuery
from skytracer.sources import kiwi as kiwi_module
from skytracer.sources.kiwi import KiwiSource
from tests.conftest import FakeHttpResponse


class _JsonResponse(FakeHttpResponse):
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        super().__init__(status_code)
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-12-14",
        return_date="2027-01-08",
        adults=1,
        cabin="economy",
        currency="USD",
    )


def test_search_normalizes_cheapest_route_and_stops(monkeypatch, query: SearchQuery) -> None:
    payload = {
        "data": [
            {
                "price": 1579.0,
                "curr": "USD",
                "deep_link": "https://kiwi.com/booking/xyz",
                "airlines": ["UA", "AC"],
                "route": [
                    {"flyFrom": "OKC", "flyTo": "DEN"},
                    {"flyFrom": "DEN", "flyTo": "NRT"},
                ],
                "duration": {"total": 36000},
            }
        ]
    }
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        captured["headers"] = headers
        return _JsonResponse(payload)

    monkeypatch.setattr(kiwi_module.httpx, "get", fake_get)
    source = KiwiSource(api_key="testkey")
    results = source.search(query)

    assert len(results) == 1
    result = results[0]
    assert result.price == 1579.0
    assert result.stops == 1
    assert result.route == "OKC → DEN → NRT"
    assert result.airlines == ["UA", "AC"]
    assert result.deep_link == "https://kiwi.com/booking/xyz"
    assert result.duration_min == 600
    assert captured["headers"] == {"apikey": "testkey"}
    assert captured["params"]["date_from"] == "14/12/2026"
    assert captured["params"]["return_from"] == "08/01/2027"


def test_search_skips_non_positive_price(monkeypatch, query: SearchQuery) -> None:
    payload = {"data": [{"price": 0, "route": []}, {"price": 500.0, "curr": "USD", "route": []}]}
    monkeypatch.setattr(kiwi_module.httpx, "get", lambda *a, **k: _JsonResponse(payload))
    source = KiwiSource(api_key="testkey")
    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 500.0


def test_search_raises_on_http_error(monkeypatch, query: SearchQuery) -> None:
    monkeypatch.setattr(
        kiwi_module.httpx, "get", lambda *a, **k: _JsonResponse({}, status_code=403)
    )
    source = KiwiSource(api_key="badkey")
    with pytest.raises(RuntimeError, match="HTTP 403"):
        source.search(query)


def test_health_check_true_when_results(monkeypatch) -> None:
    payload = {
        "data": [{"price": 300.0, "curr": "USD", "route": [{"flyFrom": "JFK", "flyTo": "LAX"}]}]
    }
    monkeypatch.setattr(kiwi_module.httpx, "get", lambda *a, **k: _JsonResponse(payload))
    source = KiwiSource(api_key="testkey")
    assert source.health_check() is True


def test_health_check_false_on_exception(monkeypatch) -> None:
    def broken(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(kiwi_module.httpx, "get", broken)
    source = KiwiSource(api_key="testkey")
    assert source.health_check() is False

from __future__ import annotations

import pytest

from skytracer.models import SearchQuery
from skytracer.sources import duffel as duffel_module
from skytracer.sources.duffel import DuffelSource
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


def test_search_normalizes_offer(monkeypatch, query: SearchQuery) -> None:
    payload = {
        "data": {
            "offers": [
                {
                    "total_amount": "1234.56",
                    "total_currency": "USD",
                    "slices": [
                        {
                            "segments": [
                                {
                                    "operating_carrier": {"name": "Duffel Airways"},
                                    "destination": {"iata_code": "DEN"},
                                    "duration": "PT2H30M",
                                },
                                {
                                    "operating_carrier": {"name": "Duffel Airways"},
                                    "destination": {"iata_code": "NRT"},
                                    "duration": "PT10H0M",
                                },
                            ]
                        }
                    ],
                }
            ]
        }
    }
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        captured["headers"] = headers
        return _JsonResponse(payload)

    monkeypatch.setattr(duffel_module.httpx, "post", fake_post)
    source = DuffelSource(api_key="duffel_test_abc")
    results = source.search(query)

    assert len(results) == 1
    result = results[0]
    assert result.price == 1234.56
    assert result.stops == 1
    assert result.route == "OKC → DEN → NRT"
    assert result.airlines == ["Duffel Airways"]
    assert result.duration_min == 750
    assert result.deep_link is None
    assert captured["headers"]["Duffel-Version"] == "v2"
    assert captured["headers"]["Authorization"] == "Bearer duffel_test_abc"
    assert len(captured["json"]["data"]["slices"]) == 2


def test_search_skips_non_positive_or_unparseable_price(monkeypatch, query: SearchQuery) -> None:
    payload = {
        "data": {
            "offers": [
                {"total_amount": "0", "slices": [{"segments": []}]},
                {"total_amount": "not-a-number", "slices": [{"segments": []}]},
                {"total_amount": "42.0", "total_currency": "USD", "slices": [{"segments": []}]},
            ]
        }
    }
    monkeypatch.setattr(duffel_module.httpx, "post", lambda *a, **k: _JsonResponse(payload))
    source = DuffelSource(api_key="key")
    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 42.0


def test_one_way_query_sends_single_slice(monkeypatch) -> None:
    one_way = SearchQuery(
        origin="OKC",
        destination="DEN",
        depart_date="2026-09-01",
        return_date=None,
        adults=1,
        cabin="economy",
        currency="USD",
    )
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _JsonResponse({"data": {"offers": []}})

    monkeypatch.setattr(duffel_module.httpx, "post", fake_post)
    source = DuffelSource(api_key="key")
    source.search(one_way)
    assert len(captured["json"]["data"]["slices"]) == 1


def test_health_check_true_when_results(monkeypatch) -> None:
    payload = {
        "data": {
            "offers": [
                {"total_amount": "300.0", "total_currency": "USD", "slices": [{"segments": []}]}
            ]
        }
    }
    monkeypatch.setattr(duffel_module.httpx, "post", lambda *a, **k: _JsonResponse(payload))
    source = DuffelSource(api_key="key")
    assert source.health_check() is True


def test_health_check_false_on_exception(monkeypatch) -> None:
    def broken(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(duffel_module.httpx, "post", broken)
    source = DuffelSource(api_key="key")
    assert source.health_check() is False

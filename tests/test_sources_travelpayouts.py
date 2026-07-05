from __future__ import annotations

import pytest

from skytracer.models import SearchQuery
from skytracer.sources import travelpayouts as tp_module
from skytracer.sources.travelpayouts import TravelpayoutsSource, _tickets
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


def test_search_normalizes_flat_list(monkeypatch, query: SearchQuery) -> None:
    payload = {
        "success": True,
        "data": [
            {
                "price": 850,
                "airline": "UA",
                "number_of_changes": 1,
                "expires_at": "2026-07-06T00:00:00Z",
            }
        ],
    }
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        captured["headers"] = headers
        return _JsonResponse(payload)

    monkeypatch.setattr(tp_module.httpx, "get", fake_get)
    source = TravelpayoutsSource(token="tok")
    results = source.search(query)

    assert len(results) == 1
    result = results[0]
    assert result.price == 850.0
    assert result.stops == 1
    assert result.airlines == ["UA"]
    assert result.deep_link is None
    assert result.raw == {"cached": True, "expires_at": "2026-07-06T00:00:00Z"}
    assert captured["headers"] == {"X-Access-Token": "tok"}


def test_search_handles_nested_dict_by_destination(monkeypatch, query: SearchQuery) -> None:
    payload = {"success": True, "data": {"NRT": {"0": {"price": 700, "airline": "JL"}}}}
    monkeypatch.setattr(tp_module.httpx, "get", lambda *a, **k: _JsonResponse(payload))
    source = TravelpayoutsSource(token="tok")
    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 700.0


def test_search_returns_empty_when_unsuccessful(monkeypatch, query: SearchQuery) -> None:
    payload = {"success": False, "error": "bad token"}
    monkeypatch.setattr(tp_module.httpx, "get", lambda *a, **k: _JsonResponse(payload))
    source = TravelpayoutsSource(token="badtoken")
    assert source.search(query) == []


def test_tickets_helper_normalizes_shapes() -> None:
    assert _tickets([{"price": 1}]) == [{"price": 1}]
    assert _tickets({"NRT": [{"price": 2}]}) == [{"price": 2}]
    assert _tickets({"NRT": {"0": {"price": 3}}}) == [{"price": 3}]
    assert _tickets("garbage") == []


def test_health_check_true_when_successful(monkeypatch) -> None:
    monkeypatch.setattr(
        tp_module.httpx, "get", lambda *a, **k: _JsonResponse({"success": True, "data": {}})
    )
    source = TravelpayoutsSource(token="tok")
    assert source.health_check() is True


def test_health_check_false_on_exception(monkeypatch) -> None:
    def broken(*a, **k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(tp_module.httpx, "get", broken)
    source = TravelpayoutsSource(token="tok")
    assert source.health_check() is False

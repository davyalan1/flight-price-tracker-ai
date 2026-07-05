from __future__ import annotations

import pytest

from skytracer.models import SearchQuery
from skytracer.sources import mcp as mcp_module
from skytracer.sources.mcp import McpSource


class _FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeToolResult:
    def __init__(self, text: str) -> None:
        self.content = [_FakeContentBlock(text)]


class _FakeSession:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.called_with: tuple[str, dict] | None = None

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def initialize(self) -> None:
        pass

    async def call_tool(self, name: str, arguments: dict) -> _FakeToolResult:
        self.called_with = (name, arguments)
        return _FakeToolResult(self._response_text)


class _FakeStreams:
    async def __aenter__(self) -> tuple:
        return ("read", "write", lambda: None)

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _patch_mcp(monkeypatch, response_text: str) -> _FakeSession:
    session = _FakeSession(response_text)
    monkeypatch.setattr(mcp_module, "streamable_http_client", lambda url: _FakeStreams())
    monkeypatch.setattr(mcp_module, "ClientSession", lambda read, write: session)
    return session


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


def test_search_parses_results_key(monkeypatch, query: SearchQuery) -> None:
    session = _patch_mcp(
        monkeypatch,
        '{"results": [{"price": 1500, "currency": "USD", "stops": 1, "route": "OKC -> NRT"}]}',
    )
    source = McpSource(endpoint="http://example.com/mcp", tool_name="search_flights")
    results = source.search(query)

    assert len(results) == 1
    assert results[0].price == 1500.0
    assert results[0].source == "mcp"
    assert session.called_with is not None
    assert session.called_with[0] == "search_flights"
    assert session.called_with[1]["origin"] == "OKC"


def test_search_accepts_bare_list(monkeypatch, query: SearchQuery) -> None:
    _patch_mcp(monkeypatch, '[{"price": 900}]')
    source = McpSource(endpoint="http://example.com/mcp")
    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 900.0


def test_search_skips_non_positive_and_non_dict_items(monkeypatch, query: SearchQuery) -> None:
    _patch_mcp(monkeypatch, '{"results": [{"price": 0}, "not-a-dict", {"price": 500}]}')
    source = McpSource(endpoint="http://example.com/mcp")
    results = source.search(query)
    assert len(results) == 1
    assert results[0].price == 500.0


def test_search_returns_empty_on_invalid_json(monkeypatch, query: SearchQuery) -> None:
    _patch_mcp(monkeypatch, "not json")
    source = McpSource(endpoint="http://example.com/mcp")
    assert source.search(query) == []


def test_search_returns_empty_on_unexpected_shape(monkeypatch, query: SearchQuery) -> None:
    _patch_mcp(monkeypatch, '{"unexpected": "shape"}')
    source = McpSource(endpoint="http://example.com/mcp")
    assert source.search(query) == []


def test_health_check_true_when_initialize_succeeds(monkeypatch) -> None:
    _patch_mcp(monkeypatch, "{}")
    source = McpSource(endpoint="http://example.com/mcp")
    assert source.health_check() is True


def test_health_check_false_on_exception(monkeypatch) -> None:
    def broken(url):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mcp_module, "streamable_http_client", broken)
    source = McpSource(endpoint="http://example.com/mcp")
    assert source.health_check() is False

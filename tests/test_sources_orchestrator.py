from __future__ import annotations

from skytracer.config import (
    DuffelSourceConfig,
    GoogleSourceConfig,
    KiwiSourceConfig,
    McpSourceConfig,
    SourcesConfig,
    TravelpayoutsSourceConfig,
)
from skytracer.models import FareResult, SearchQuery
from skytracer.sources.orchestrator import build_enabled_sources, search_all


def _sources_config(**enabled: bool) -> SourcesConfig:
    return SourcesConfig(
        google=GoogleSourceConfig(
            enabled=enabled.get("google", False), use_browser_fallback=False
        ),
        kiwi=KiwiSourceConfig(enabled=enabled.get("kiwi", False), api_key="key"),
        travelpayouts=TravelpayoutsSourceConfig(
            enabled=enabled.get("travelpayouts", False), token="tok"
        ),
        duffel=DuffelSourceConfig(enabled=enabled.get("duffel", False), api_key="key"),
        mcp=McpSourceConfig(
            enabled=enabled.get("mcp", False), endpoint="http://example.com", tool_name="search"
        ),
    )


def test_build_enabled_sources_only_returns_toggled_on() -> None:
    sources = build_enabled_sources(_sources_config(kiwi=True, duffel=True))
    names = {s.name for s in sources}
    assert names == {"kiwi", "duffel"}


def test_build_enabled_sources_none_enabled_returns_empty() -> None:
    assert build_enabled_sources(_sources_config()) == []


def test_search_all_combines_results_across_sources() -> None:
    class _Fake:
        def __init__(self, name: str, price: float) -> None:
            self.name = name
            self.enabled = True
            self.requires_key = False
            self._price = price

        def search(self, q: SearchQuery) -> list[FareResult]:
            return [
                FareResult(
                    price=self._price,
                    currency="USD",
                    airlines=[],
                    stops=0,
                    duration_min=None,
                    route="OKC → NRT",
                    source=self.name,
                )
            ]

        def health_check(self) -> bool:
            return True

    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-12-14",
        return_date="2027-01-08",
        adults=1,
        cabin="economy",
        currency="USD",
    )
    results = search_all([_Fake("a", 100.0), _Fake("b", 50.0)], query)
    assert sorted(r.price for r in results) == [50.0, 100.0]


def test_search_all_skips_source_that_raises() -> None:
    class _Broken:
        name = "broken"
        enabled = True
        requires_key = False

        def search(self, q: SearchQuery) -> list[FareResult]:
            raise RuntimeError("boom")

        def health_check(self) -> bool:
            return False

    class _Ok:
        name = "ok"
        enabled = True
        requires_key = False

        def search(self, q: SearchQuery) -> list[FareResult]:
            return [
                FareResult(
                    price=200.0,
                    currency="USD",
                    airlines=[],
                    stops=0,
                    duration_min=None,
                    route="OKC → NRT",
                    source="ok",
                )
            ]

        def health_check(self) -> bool:
            return True

    query = SearchQuery(
        origin="OKC",
        destination="NRT",
        depart_date="2026-12-14",
        return_date="2027-01-08",
        adults=1,
        cabin="economy",
        currency="USD",
    )
    results = search_all([_Broken(), _Ok()], query)
    assert len(results) == 1
    assert results[0].price == 200.0

from __future__ import annotations

from skytracer.ai.answer import build_backend
from skytracer.ai.anthropic_backend import AnthropicBackend
from skytracer.ai.context import build_grounding_context
from skytracer.ai.ollama_backend import OllamaBackend
from skytracer.db import init_db
from skytracer.models import FareResult, SearchQuery
from skytracer.observations import insert_observation
from tests.conftest import default_ai_config


def test_build_grounding_context_with_no_data(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    assert "No tracked routes" in build_grounding_context(conn)


def test_build_grounding_context_includes_stats_and_alerts(tmp_path) -> None:
    conn = init_db(tmp_path / "skytracer.db")
    query = SearchQuery(
        origin="OKC", destination="NRT", depart_date="2026-09-01", return_date="2026-09-11",
        adults=1, cabin="economy", currency="USD",
    )
    insert_observation(
        conn, route_key="OKC-NRT", query=query,
        result=FareResult(
            price=1200.0, currency="USD", airlines=["ANA"], stops=1,
            duration_min=600, route="OKC → NRT", source="google",
        ),
        observed_at="2026-01-01T00:00:00+00:00",
    )

    context = build_grounding_context(conn)
    assert "OKC-NRT" in context
    assert "1200.00" in context
    assert "Recent alerts: none" in context


def test_build_backend_picks_ollama_by_default() -> None:
    backend = build_backend(default_ai_config(provider="ollama"))
    assert isinstance(backend, OllamaBackend)
    assert backend.base_url == "http://localhost:11434/v1"
    assert backend.model == "llama3"


def test_build_backend_picks_anthropic_when_configured() -> None:
    backend = build_backend(default_ai_config(provider="anthropic", anthropic_api_key="sk-test"))
    assert isinstance(backend, AnthropicBackend)
    assert backend.api_key == "sk-test"

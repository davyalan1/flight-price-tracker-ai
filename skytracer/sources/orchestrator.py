"""Fans a search out across every enabled fare source and combines the
results — poller.py picks the cheapest across the combined list, same as it
already did for Google-only results.
"""

from __future__ import annotations

import logging

from skytracer.config import SourcesConfig
from skytracer.models import FareResult, SearchQuery
from skytracer.sources import FareSource
from skytracer.sources.duffel import DuffelSource
from skytracer.sources.google import GoogleFlightsSource
from skytracer.sources.kiwi import KiwiSource
from skytracer.sources.mcp import McpSource
from skytracer.sources.travelpayouts import TravelpayoutsSource

logger = logging.getLogger("skytracer.sources.orchestrator")


def build_enabled_sources(sources: SourcesConfig) -> list[FareSource]:
    candidates: list[FareSource] = [
        GoogleFlightsSource(
            enabled=sources.google.enabled,
            use_browser_fallback=sources.google.use_browser_fallback,
        ),
        KiwiSource(enabled=sources.kiwi.enabled, api_key=sources.kiwi.api_key),
        TravelpayoutsSource(
            enabled=sources.travelpayouts.enabled, token=sources.travelpayouts.token
        ),
        DuffelSource(enabled=sources.duffel.enabled, api_key=sources.duffel.api_key),
        McpSource(
            enabled=sources.mcp.enabled,
            endpoint=sources.mcp.endpoint,
            tool_name=sources.mcp.tool_name,
        ),
    ]
    return [source for source in candidates if source.enabled]


def search_all(sources: list[FareSource], query: SearchQuery) -> list[FareResult]:
    """Query every source, logging and skipping any that fail — one broken
    optional source shouldn't take down a poll that other sources can still
    serve.
    """
    fares: list[FareResult] = []
    for source in sources:
        try:
            fares.extend(source.search(query))
        except Exception:
            logger.exception("poll: %s source failed", source.name)
    return fares

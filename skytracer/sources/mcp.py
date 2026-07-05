"""MCP (Model Context Protocol) source. Points at a user-run MCP server
exposing an arbitrary flight-search tool. There's no standard tool name or
result schema across MCP servers, so this adapter is deliberately the least
strict: a configurable `tool_name` and best-effort parsing of whatever comes
back, logging clearly (never raising) when the shape doesn't match what a
flight-search tool would be expected to return.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from skytracer.models import FareResult, SearchQuery

logger = logging.getLogger("skytracer.sources.mcp")


@dataclass
class McpSource:
    endpoint: str = ""
    tool_name: str = "search_flights"
    enabled: bool = True
    name: str = field(default="mcp", init=False)
    requires_key: bool = field(default=False, init=False)

    def search(self, q: SearchQuery) -> list[FareResult]:
        arguments = {
            "origin": q.origin,
            "destination": q.destination,
            "depart_date": q.depart_date,
            "return_date": q.return_date,
            "adults": q.adults,
            "cabin": q.cabin,
            "currency": q.currency,
        }
        text = asyncio.run(self._call_tool(arguments))
        return self._parse_results(text, q)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        async with streamable_http_client(self.endpoint) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _call_tool(self, arguments: dict) -> str:
        async with self._session() as session:
            result = await session.call_tool(self.tool_name, arguments)
            texts = [block.text for block in result.content if hasattr(block, "text")]
            return "\n".join(texts)

    def _parse_results(self, text: str, q: SearchQuery) -> list[FareResult]:
        try:
            data = json.loads(text)
        except ValueError as exc:
            logger.warning("mcp: tool %r response wasn't valid JSON: %s", self.tool_name, exc)
            return []

        if isinstance(data, dict):
            items = data.get("results")
        elif isinstance(data, list):
            items = data
        else:
            items = None
        if not isinstance(items, list):
            logger.warning(
                "mcp: unexpected response shape from tool %r: %r", self.tool_name, data
            )
            return []

        fares: list[FareResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            price = item.get("price")
            if not isinstance(price, int | float) or price <= 0:
                continue
            fares.append(
                FareResult(
                    price=float(price),
                    currency=item.get("currency", q.currency),
                    airlines=list(item.get("airlines") or []),
                    stops=int(item.get("stops") or 0),
                    duration_min=item.get("duration_min"),
                    route=item.get("route") or f"{q.origin} → {q.destination}",
                    source=self.name,
                    deep_link=item.get("deep_link"),
                    raw=item,
                )
            )
        return fares

    def health_check(self) -> bool:
        try:
            asyncio.run(self._probe())
            return True
        except Exception as exc:  # noqa: BLE001 - health_check must never raise
            logger.warning("mcp: health_check failed: %s", exc)
            return False

    async def _probe(self) -> None:
        async with self._session():
            pass

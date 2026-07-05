"""Kiwi.com Tequila API source. Requires a partner-issued API key — register
at tequila.kiwi.com. See PHASE6_RESEARCH.md: dev-key access and rate limits
weren't confirmed against a live key while writing this, so treat the first
real "Test source" click as the actual verification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from skytracer.models import FareResult, SearchQuery

logger = logging.getLogger("skytracer.sources.kiwi")

BASE_URL = "https://api.tequila.kiwi.com/v2/search"
TIMEOUT_SECONDS = 20.0


def _ddmmyyyy(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d/%m/%Y")


@dataclass
class KiwiSource:
    api_key: str = ""
    enabled: bool = True
    name: str = field(default="kiwi", init=False)
    requires_key: bool = field(default=True, init=False)

    def search(self, q: SearchQuery) -> list[FareResult]:
        params = {
            "fly_from": q.origin,
            "fly_to": q.destination,
            "date_from": _ddmmyyyy(q.depart_date),
            "date_to": _ddmmyyyy(q.depart_date),
            "curr": q.currency,
            "adults": q.adults,
            "limit": 20,
        }
        if q.return_date:
            params["return_from"] = _ddmmyyyy(q.return_date)
            params["return_to"] = _ddmmyyyy(q.return_date)

        response = httpx.get(
            BASE_URL, params=params, headers={"apikey": self.api_key}, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload = response.json()

        fares: list[FareResult] = []
        for flight in payload.get("data", []):
            price = flight.get("price")
            if not isinstance(price, int | float) or price <= 0:
                continue
            segments = flight.get("route") or []
            stops = max(len(segments) - 1, 0)
            codes = (
                [segments[0].get("flyFrom", "")] + [seg.get("flyTo", "") for seg in segments]
                if segments
                else []
            )
            airlines = flight.get("airlines") or sorted(
                {seg.get("airline", "") for seg in segments} - {""}
            )
            fares.append(
                FareResult(
                    price=float(price),
                    currency=flight.get("curr", q.currency),
                    airlines=list(airlines),
                    stops=stops,
                    duration_min=self._duration_min(flight),
                    route=" → ".join(codes) if codes else f"{q.origin} → {q.destination}",
                    source=self.name,
                    deep_link=flight.get("deep_link"),
                    raw=None,
                )
            )
        return fares

    @staticmethod
    def _duration_min(flight: dict) -> int | None:
        duration = flight.get("duration")
        if isinstance(duration, dict) and isinstance(duration.get("total"), int | float):
            return int(duration["total"] // 60)
        return None

    def health_check(self) -> bool:
        probe = SearchQuery(
            origin="JFK",
            destination="LAX",
            depart_date=(date.today() + timedelta(days=30)).isoformat(),
            return_date=None,
            adults=1,
            cabin="economy",
            currency="USD",
        )
        try:
            return len(self.search(probe)) > 0
        except Exception as exc:  # noqa: BLE001 - health_check must never raise
            logger.warning("kiwi: health_check failed: %s", exc)
            return False

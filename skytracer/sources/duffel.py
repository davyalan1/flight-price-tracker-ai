"""Duffel API (v2) source. Free `duffel_test_...` tokens (from the Duffel
dashboard, no payment/production account needed) return realistic-shaped fake
offers from "Duffel Airways" — this is the one optional source that can
actually be tested live, same as Google. Duffel is API-only booking (no
public deep link), so `FareResult.deep_link` is always None here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from skytracer.models import FareResult, SearchQuery

logger = logging.getLogger("skytracer.sources.duffel")

BASE_URL = "https://api.duffel.com/air/offer_requests"
TIMEOUT_SECONDS = 30.0

_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def _duration_min(value: str | None) -> int:
    if not value:
        return 0
    match = _ISO8601_DURATION_RE.match(value)
    if not match:
        return 0
    hours, minutes = match.groups()
    return int(hours or 0) * 60 + int(minutes or 0)


@dataclass
class DuffelSource:
    api_key: str = ""
    enabled: bool = True
    name: str = field(default="duffel", init=False)
    requires_key: bool = field(default=True, init=False)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def search(self, q: SearchQuery) -> list[FareResult]:
        slices = [
            {"origin": q.origin, "destination": q.destination, "departure_date": q.depart_date}
        ]
        if q.return_date:
            slices.append(
                {
                    "origin": q.destination,
                    "destination": q.origin,
                    "departure_date": q.return_date,
                }
            )
        body = {
            "data": {
                "passengers": [{"type": "adult"}] * q.adults,
                "slices": slices,
                "cabin_class": q.cabin,
            }
        }
        response = httpx.post(BASE_URL, json=body, headers=self._headers(), timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        offers = (response.json().get("data") or {}).get("offers") or []

        fares: list[FareResult] = []
        for offer in offers:
            price = offer.get("total_amount")
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            outbound = (offer.get("slices") or [{}])[0]
            segments = outbound.get("segments") or []
            airlines = sorted(
                {
                    seg.get("operating_carrier", {}).get("name", "")
                    for seg in segments
                    if seg.get("operating_carrier", {}).get("name")
                }
            )
            duration_min = sum(_duration_min(seg.get("duration")) for seg in segments) or None
            fares.append(
                FareResult(
                    price=price,
                    currency=offer.get("total_currency", q.currency),
                    airlines=airlines,
                    stops=max(len(segments) - 1, 0),
                    duration_min=duration_min,
                    route=self._route(q, segments),
                    source=self.name,
                    deep_link=None,
                    raw=None,
                )
            )
        return fares

    @staticmethod
    def _route(q: SearchQuery, segments: list[dict]) -> str:
        if not segments:
            return f"{q.origin} → {q.destination}"
        codes = [q.origin]
        for seg in segments:
            dest = (seg.get("destination") or {}).get("iata_code")
            if dest:
                codes.append(dest)
        return " → ".join(codes)

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
            logger.warning("duffel: health_check failed: %s", exc)
            return False

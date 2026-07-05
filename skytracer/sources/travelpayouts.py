"""Travelpayouts Data API source. Uses `/v1/prices/cheap`, which returns
other travelers' recently *cached* fares (up to ~48h stale per Travelpayouts'
own docs) rather than a live quote — there's no live-search endpoint reachable
without 50k+ monthly active users. Every result is tagged `raw={"cached":
True, ...}` so the dashboard can flag it as such later (Phase 8), per the
build spec's own anticipation of this in its notify-of-caveats note.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

from skytracer.models import FareResult, SearchQuery

logger = logging.getLogger("skytracer.sources.travelpayouts")

BASE_URL = "https://api.travelpayouts.com/v1/prices/cheap"
TIMEOUT_SECONDS = 20.0

# A canonical high-traffic route, used only for health_check — this API is
# cache-based, so a real trip's origin/destination may simply have no recent
# cached fares, which would otherwise read as a false "unreachable".
PROBE_ORIGIN = "MOW"
PROBE_DESTINATION = "LED"


def _tickets(data: object) -> list[dict]:
    """Travelpayouts nests `data` by destination (and sometimes further by
    stop count) rather than returning a flat list — normalize defensively
    since the exact nesting isn't guaranteed across routes/plans.
    """
    if isinstance(data, list):
        out: list[dict] = []
        for item in data:
            out.extend(_tickets(item))
        return out
    if isinstance(data, dict):
        if "price" in data:
            return [data]
        out = []
        for value in data.values():
            out.extend(_tickets(value))
        return out
    return []


@dataclass
class TravelpayoutsSource:
    token: str = ""
    enabled: bool = True
    name: str = field(default="travelpayouts", init=False)
    requires_key: bool = field(default=True, init=False)

    def search(self, q: SearchQuery) -> list[FareResult]:
        params = {
            "origin": q.origin,
            "destination": q.destination,
            "depart_date": q.depart_date,
            "currency": q.currency.lower(),
        }
        if q.return_date:
            params["return_date"] = q.return_date

        response = httpx.get(
            BASE_URL,
            params=params,
            headers={"X-Access-Token": self.token},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            logger.warning("travelpayouts: request unsuccessful: %s", payload.get("error"))
            return []

        fares: list[FareResult] = []
        for ticket in _tickets(payload.get("data")):
            price = ticket.get("price")
            if not isinstance(price, int | float) or price <= 0:
                continue
            stops = ticket.get("number_of_changes", 0)
            airline = ticket.get("airline")
            fares.append(
                FareResult(
                    price=float(price),
                    currency=q.currency,
                    airlines=[airline] if airline else [],
                    stops=int(stops) if isinstance(stops, int) else 0,
                    duration_min=None,
                    route=f"{q.origin} → {q.destination}",
                    source=self.name,
                    deep_link=None,
                    raw={"cached": True, "expires_at": ticket.get("expires_at")},
                )
            )
        return fares

    def health_check(self) -> bool:
        try:
            response = httpx.get(
                BASE_URL,
                params={
                    "origin": PROBE_ORIGIN,
                    "destination": PROBE_DESTINATION,
                    "depart_date": (date.today() + timedelta(days=30)).isoformat(),
                    "currency": "usd",
                },
                headers={"X-Access-Token": self.token},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return bool(response.json().get("success"))
        except Exception as exc:  # noqa: BLE001 - health_check must never raise
            logger.warning("travelpayouts: health_check failed: %s", exc)
            return False

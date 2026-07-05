"""Google Flights source via the `faster-flights` package (imports as
`fast_flights`). No API key required — this is the only source that must
work standalone.

Built against faster-flights==3.7.0's v3 API: `create_query()` builds a
`Query`, `get_flights(query)` fetches results. For round trips we pass both
legs into one `create_query(..., trip="round-trip")` call — Google bundles
the total round-trip price into each returned "departing flight" card, so a
single `get_flights()` call (no leg-by-leg selection dance) already gives a
real total price. Verified live against OKC->NRT before writing this.

`stops`/`route`/`duration_min` reflect the outbound leg's segments, since
that's the only leg faster-flights' bundled round-trip response itemizes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import fast_flights as ff

from skytracer.models import FareResult, SearchQuery

logger = logging.getLogger("skytracer.sources.google")

CABIN_MAP = {
    "economy": "economy",
    "premium_economy": "premium-economy",
    "business": "business",
    "first": "first",
}

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class GoogleFlightsSource:
    enabled: bool = True
    use_browser_fallback: bool = True
    name: str = field(default="google", init=False)
    requires_key: bool = field(default=False, init=False)

    def _build_query(self, q: SearchQuery) -> ff.Query:
        legs = [ff.FlightQuery(date=q.depart_date, from_airport=q.origin, to_airport=q.destination)]
        trip = "one-way"
        if q.return_date:
            legs.append(
                ff.FlightQuery(date=q.return_date, from_airport=q.destination, to_airport=q.origin)
            )
            trip = "round-trip"
        return ff.create_query(
            flights=legs,
            trip=trip,
            seat=CABIN_MAP.get(q.cabin, "economy"),
            passengers=ff.Passengers(adults=q.adults),
            currency=q.currency,
        )

    def _fetch_with_retry(self, query: ff.Query) -> list:
        last_exc: Exception | None = None
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                results = ff.get_flights(query)
                if results:
                    return list(results)
                logger.warning(
                    "google: empty result on attempt %d/%d (cold cache?)", attempt, RETRY_ATTEMPTS
                )
            except Exception as exc:  # noqa: BLE001 - network/library errors, retried below
                last_exc = exc
                logger.warning(
                    "google: fetch failed on attempt %d/%d: %s", attempt, RETRY_ATTEMPTS, exc
                )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        if last_exc is not None:
            raise last_exc
        return []

    def _browser_fallback(self, query: ff.Query) -> list | None:
        try:
            from fast_flights.browser import capture_browser_artifacts
            from fast_flights.shopping import _extract_full_flights_list
        except ImportError:
            logger.warning(
                "google: browser fallback unavailable (playwright not installed — "
                "run `playwright install --with-deps chromium` to enable it)"
            )
            return None
        capture = capture_browser_artifacts(query.url())
        if capture is None or not capture.has_captured_response:
            logger.warning("google: browser fallback did not capture a response")
            return None
        try:
            flights = _extract_full_flights_list(
                capture.captured_response_text, source="browser-capture"
            )
        except Exception as exc:  # noqa: BLE001 - best-effort fallback, never fatal
            logger.warning("google: failed to parse browser-captured response: %s", exc)
            return None
        return list(flights) if flights else None

    def search(self, q: SearchQuery) -> list[FareResult]:
        query = self._build_query(q)
        results = self._fetch_with_retry(query)
        if not results and self.use_browser_fallback:
            logger.info("google: RPC path empty after retries, trying browser fallback")
            browser_results = self._browser_fallback(query)
            if browser_results:
                results = browser_results

        deep_link = query.url()
        fares: list[FareResult] = []
        for flight in results:
            if flight.price <= 0:
                # A malformed/placeholder card would otherwise win min() in
                # poller.py outright and permanently poison all-time-low.
                logger.warning("google: skipping fare with non-positive price: %r", flight.price)
                continue
            stops = max(len(flight.flights) - 1, 0)
            codes = [flight.flights[0].from_airport.code]
            codes += [seg.to_airport.code for seg in flight.flights]
            route = " → ".join(codes)
            duration_min = sum(seg.duration for seg in flight.flights) or None
            fares.append(
                FareResult(
                    price=float(flight.price),
                    currency=q.currency,
                    airlines=list(flight.airlines),
                    stops=stops,
                    duration_min=duration_min,
                    route=route,
                    source=self.name,
                    deep_link=deep_link,
                    raw=None,
                )
            )
        return fares

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
            logger.warning("google: health_check failed: %s", exc)
            return False

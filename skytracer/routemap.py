"""Fully offline flight-route diagram: dots + a connecting line for the
airports in a route string (e.g. "OKC-ORD-NRT"), drawn as inline SVG. No
network access, no JS — same philosophy as charts.py's price history chart.

The coordinate table below covers the world's major airports and hubs, not
the full ~7,500-row OurAirports dataset — this app only ever needs to plot
codes that a real fare search actually returned (origin/destination plus
whatever connecting hubs Google/Kiwi/Duffel/Travelpayouts/MCP surface), and
an unrecognized code degrades gracefully (see render_route_svg) rather than
crashing the page.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("skytracer.routemap")

WIDTH = 600
HEIGHT = 260
PADDING = 30

# (lat, lon) for major airports. Extend this table if a real route surfaces
# an unlisted code — render_route_svg() logs which one and returns None
# rather than crashing.
AIRPORTS: dict[str, tuple[float, float]] = {
    "OKC": (35.3931, -97.6007),
    "DFW": (32.8998, -97.0403),
    "IAH": (29.9902, -95.3368),
    "ORD": (41.9742, -87.9073),
    "DEN": (39.8561, -104.6737),
    "LAX": (33.9416, -118.4085),
    "SFO": (37.6213, -122.3790),
    "SEA": (47.4502, -122.3088),
    "JFK": (40.6413, -73.7781),
    "EWR": (40.6895, -74.1745),
    "ATL": (33.6407, -84.4277),
    "MSP": (44.8848, -93.2223),
    "PHX": (33.4373, -112.0078),
    "LAS": (36.0840, -115.1537),
    "MIA": (25.7959, -80.2870),
    "HND": (35.5494, 139.7798),
    "NRT": (35.7647, 140.3864),
    "KIX": (34.4347, 135.2441),
    "ICN": (37.4602, 126.4407),
    "GMP": (37.5583, 126.7906),
    "PVG": (31.1443, 121.8083),
    "PEK": (40.0801, 116.5846),
    "HKG": (22.3080, 113.9185),
    "TPE": (25.0777, 121.2328),
    "SIN": (1.3644, 103.9915),
    "BKK": (13.6900, 100.7501),
    "NGO": (34.8584, 136.8054),
    "FUK": (33.5859, 130.4510),
    "CTS": (42.7752, 141.6923),
    "LHR": (51.4700, -0.4543),
    "CDG": (49.0097, 2.5479),
    "FRA": (50.0379, 8.5622),
    "AMS": (52.3105, 4.7683),
    "DXB": (25.2532, 55.3657),
    "YYZ": (43.6777, -79.6248),
    "YVR": (49.1967, -123.1815),
    "MEX": (19.4363, -99.0721),
    "GRU": (-23.4356, -46.4731),
    "SYD": (-33.9399, 151.1753),
    "MEL": (-37.6690, 144.8410),
    "HNL": (21.3187, -157.9224),
}


def _project(
    lat: float, lon: float, bounds: tuple[float, float, float, float]
) -> tuple[float, float]:
    min_lat, max_lat, min_lon, max_lon = bounds
    lon_span = (max_lon - min_lon) or 1.0
    lat_span = (max_lat - min_lat) or 1.0
    x = PADDING + (WIDTH - 2 * PADDING) * (lon - min_lon) / lon_span
    y = PADDING + (HEIGHT - 2 * PADDING) * (max_lat - lat) / lat_span
    return x, y


def coords_for(codes: list[str]) -> list[dict[str, float | str]] | None:
    """Same lookup/validation as render_route_svg, but returns plain
    (code, lat, lon) dicts for the optional client-side Leaflet map instead
    of an SVG string.
    """
    if any(code not in AIRPORTS for code in codes) or len(codes) < 2:
        return None
    return [{"code": code, "lat": AIRPORTS[code][0], "lon": AIRPORTS[code][1]} for code in codes]


def render_route_svg(codes: list[str]) -> str | None:
    """codes: IATA airport codes in itinerary order, e.g. ["OKC", "ORD", "NRT"].
    Returns None (logging which code was the problem) if any isn't in the
    vendored table, or if fewer than 2 usable codes are given.
    """
    coords = []
    for code in codes:
        if code not in AIRPORTS:
            logger.warning("routemap: no coordinates for airport code %r, skipping map", code)
            return None
        coords.append((code, *AIRPORTS[code]))

    if len(coords) < 2:
        return None

    lats = [c[1] for c in coords]
    lons = [c[2] for c in coords]
    bounds = (min(lats), max(lats), min(lons), max(lons))

    points = [_project(lat, lon, bounds) for _, lat, lon in coords]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    dots = []
    labels = []
    for (code, _, _), (x, y) in zip(coords, points, strict=True):
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="route-dot"/>')
        labels.append(
            f'<text x="{x:.1f}" y="{y - 10:.1f}" class="route-label" '
            f'text-anchor="middle">{code}</text>'
        )

    return (
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="route-map" role="img" '
        f'aria-label="Flight route: {" to ".join(c[0] for c in coords)}">'
        f'<polyline points="{polyline}" class="route-line" fill="none"/>'
        + "".join(dots)
        + "".join(labels)
        + "</svg>"
    )

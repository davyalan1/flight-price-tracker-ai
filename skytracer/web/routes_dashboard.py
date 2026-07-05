"""Read-only Dashboard — no login required (only Settings is gated)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from skytracer import stats as stats_module
from skytracer.alerts import fetch_alert_history
from skytracer.charts import render_price_history_svg
from skytracer.observations import (
    fetch_latest_observation,
    fetch_observations,
    fetch_price_points,
    fetch_top_n_for_latest_poll,
    list_route_keys,
)
from skytracer.routemap import coords_for, render_route_svg
from skytracer.settings_store import as_config
from skytracer.web import auth
from skytracer.web.deps import ConnDep
from skytracer.web.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn: ConnDep):
    rows = []
    for route_key in list_route_keys(conn):
        points = fetch_price_points(conn, route_key)
        route_stats = stats_module.compute_stats(route_key, points)
        latest = fetch_latest_observation(conn, route_key)
        if route_stats is None or latest is None:
            continue
        rows.append(
            {
                "route_key": route_key,
                "current_price": route_stats.current_price,
                "all_time_low": route_stats.all_time_low,
                "trend": route_stats.trend,
                "currency": latest["currency"],
                "source": latest["source"],
                "last_updated": route_stats.current_observed_at,
            }
        )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"logged_in": auth.is_logged_in(conn, request), "routes": rows},
    )


@router.get("/route/{route_key}", response_class=HTMLResponse)
def route_detail(route_key: str, request: Request, conn: ConnDep):
    points = fetch_price_points(conn, route_key)
    route_stats = stats_module.compute_stats(route_key, points)
    observations = []
    for row in fetch_observations(conn, route_key):
        observations.append(
            {
                "observed_at": row["observed_at"],
                "price": row["price"],
                "currency": row["currency"],
                "stops": row["stops"],
                "airlines": ", ".join(json.loads(row["airlines"])) if row["airlines"] else "",
                "source": row["source"],
                "deep_link": row["deep_link"],
            }
        )
    stats_ctx = None
    if route_stats is not None:
        stats_ctx = {
            "current_price": route_stats.current_price,
            "all_time_low": route_stats.all_time_low,
            "all_time_high": route_stats.all_time_high,
            "low_30d": route_stats.low_30d,
            "trend": route_stats.trend,
            "currency": observations[0]["currency"] if observations else "",
        }

    config_top_n = as_config(conn).dashboard.top_n_fares
    top_fares = [
        {
            "price": row["price"],
            "currency": row["currency"],
            "stops": row["stops"],
            "airlines": ", ".join(json.loads(row["airlines"])) if row["airlines"] else "",
            "source": row["source"],
            "deep_link": row["deep_link"],
            "route": row["route"],
        }
        for row in fetch_top_n_for_latest_poll(conn, route_key, config_top_n)
    ]
    route_codes = top_fares[0]["route"].split(" → ") if top_fares else []
    route_map_svg = render_route_svg(route_codes) if route_codes else None
    route_map_coords = coords_for(route_codes) if route_codes else None
    alert_history = [
        {"sent_at": row["sent_at"], "reason": row["reason"], "price": row["price"]}
        for row in fetch_alert_history(conn, route_key)
    ]

    return templates.TemplateResponse(
        request,
        "route_detail.html",
        {
            "logged_in": auth.is_logged_in(conn, request),
            "route_key": route_key,
            "stats": stats_ctx,
            "observations": observations,
            "chart_svg": render_price_history_svg(points),
            "top_fares": top_fares,
            "route_map_svg": route_map_svg,
            "route_map_coords": route_map_coords,
            "alert_history": alert_history,
        },
    )

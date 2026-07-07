"""The Settings page: the one place a non-technical user changes anything.

POST /settings handles three different submit buttons from the same form
(save / test_source / test_notify) so a source or notification channel can
be tested using whatever the user just typed, without first requiring a
full-form save.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import FormData

from skytracer import settings_store
from skytracer.config import ConfigError, validate
from skytracer.models import Alert
from skytracer.notify import build_notifier
from skytracer.poller import run_poll_once
from skytracer.settings_store import SECRET_KEYS, as_dict, save_config
from skytracer.sources import FareSource
from skytracer.sources.duffel import DuffelSource
from skytracer.sources.google import GoogleFlightsSource
from skytracer.sources.kiwi import KiwiSource
from skytracer.sources.mcp import McpSource
from skytracer.sources.travelpayouts import TravelpayoutsSource
from skytracer.web import auth
from skytracer.web.deps import SettingsConnDep
from skytracer.web.templating import templates

router = APIRouter()

FIELD_TOKENS = sorted(
    [
        "schedule.every_hours",
        "dashboard.top_n_fares",
        "ai.provider",
        "sources.kiwi",
        "sources.travelpayouts",
        "sources.duffel",
        "sources.mcp",
        "notify.channel",
    ],
    key=len,
    reverse=True,
)

# Matches validate()'s per-trip error prefix, e.g. "trips[0].origin: ..." or
# "trips[0].alerts.threshold_price must be ..." or the bare
# "trips[0]: enable exactly one of fixed or flexible ..." — captures the
# index and (if present) the dotted field path so each error can be
# attached to the right trip card and field, not just a general banner.
_TRIP_ERROR_RE = re.compile(r"^trips\[(\d+)\](?:\.([\w.]+))?")


def _map_errors_to_fields(messages: list[str]) -> dict[str, list[str]]:
    field_errors: dict[str, list[str]] = {}
    for message in messages:
        trip_match = _TRIP_ERROR_RE.match(message)
        if trip_match:
            index, field = trip_match.groups()
            if field is None:
                key = f"trips.{index}"
            elif field.startswith("alerts."):
                key = f"trips.{index}.{field}"
            else:
                key = f"trips.{index}.trip.{field}"
        else:
            key = next((token for token in FIELD_TOKENS if token in message), "_general")
        field_errors.setdefault(key, []).append(message)
    return field_errors


def _checkbox(form: FormData, name: str) -> bool:
    return name in form


def _secret_or_existing(form: FormData, name: str, existing: str) -> str:
    value = form.get(name, "")
    return str(value) if value else existing


def _coerce_int(raw: Any) -> Any:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw


def _coerce_number(raw: Any) -> Any:
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    try:
        return float(raw)
    except (TypeError, ValueError):
        return raw


def _secrets_set(conn: sqlite3.Connection) -> dict[str, bool]:
    return {
        key: bool(settings_store.get(conn, key, ""))
        for key in SECRET_KEYS
        if key != "web.admin_password"
    }


_TRIP_INDEX_RE = re.compile(r"^trips\.(\d+)\.")


def _blank_trip_entry() -> dict:
    """Defaults for a freshly-added trip card — enough to render sensibly,
    but origin/destination are deliberately blank so the user must fill
    them in (and validate() will reject an empty save) rather than silently
    tracking a copy of the previous trip.
    """
    return {
        "trip": {
            "origin": "",
            "destination": "",
            "adults": 1,
            "cabin": "economy",
            "currency": "USD",
            "fixed": {"enabled": True, "depart_date": "", "return_date": ""},
            "flexible": {
                "enabled": False,
                "earliest_depart": "",
                "latest_depart": "",
                "trip_length_days": 7,
                "scan_step_days": 3,
            },
        },
        "alerts": {
            "threshold_price": 1000,
            "drop_percent": 5,
            "notify_on_new_low": True,
            "cooldown_hours": 12,
        },
    }


def _merge_one_trip(form: FormData, index: int, existing: dict) -> dict:
    prefix = f"trips.{index}."
    default_mode = "fixed" if existing["trip"]["fixed"]["enabled"] else "flexible"
    mode = form.get(f"{prefix}mode", default_mode)
    return {
        "trip": {
            "origin": str(form.get(f"{prefix}trip.origin", existing["trip"]["origin"])).upper(),
            "destination": str(
                form.get(f"{prefix}trip.destination", existing["trip"]["destination"])
            ).upper(),
            "adults": _coerce_int(form.get(f"{prefix}trip.adults", existing["trip"]["adults"])),
            "cabin": form.get(f"{prefix}trip.cabin", existing["trip"]["cabin"]),
            "currency": str(
                form.get(f"{prefix}trip.currency", existing["trip"]["currency"])
            ).upper(),
            "fixed": {
                "enabled": mode == "fixed",
                "depart_date": form.get(
                    f"{prefix}trip.fixed.depart_date", existing["trip"]["fixed"]["depart_date"]
                ),
                "return_date": form.get(
                    f"{prefix}trip.fixed.return_date", existing["trip"]["fixed"]["return_date"]
                ),
            },
            "flexible": {
                "enabled": mode == "flexible",
                "earliest_depart": form.get(
                    f"{prefix}trip.flexible.earliest_depart",
                    existing["trip"]["flexible"]["earliest_depart"],
                ),
                "latest_depart": form.get(
                    f"{prefix}trip.flexible.latest_depart",
                    existing["trip"]["flexible"]["latest_depart"],
                ),
                "trip_length_days": _coerce_int(
                    form.get(
                        f"{prefix}trip.flexible.trip_length_days",
                        existing["trip"]["flexible"]["trip_length_days"],
                    )
                ),
                "scan_step_days": _coerce_int(
                    form.get(
                        f"{prefix}trip.flexible.scan_step_days",
                        existing["trip"]["flexible"]["scan_step_days"],
                    )
                ),
            },
        },
        "alerts": {
            "threshold_price": _coerce_number(
                form.get(f"{prefix}alerts.threshold_price", existing["alerts"]["threshold_price"])
            ),
            "drop_percent": _coerce_number(
                form.get(f"{prefix}alerts.drop_percent", existing["alerts"]["drop_percent"])
            ),
            "notify_on_new_low": _checkbox(form, f"{prefix}alerts.notify_on_new_low"),
            "cooldown_hours": _coerce_number(
                form.get(f"{prefix}alerts.cooldown_hours", existing["alerts"]["cooldown_hours"])
            ),
        },
    }


def _merge_trips_from_form(form: FormData, stored_trips: list[dict]) -> list[dict]:
    """Discover which trip indices were actually submitted (from the field
    names themselves, e.g. "trips.0.trip.origin") rather than assuming the
    stored count — the form is the source of truth for how many trip cards
    exist right now, since add-trip/remove-trip change that count between
    page loads.
    """
    indices = sorted({int(m.group(1)) for key in form if (m := _TRIP_INDEX_RE.match(key))})
    return [
        _merge_one_trip(
            form, i, stored_trips[i] if i < len(stored_trips) else _blank_trip_entry()
        )
        for i in indices
    ]


def _merge_settings_from_form(form: FormData, stored: dict) -> dict:
    return {
        "trips": _merge_trips_from_form(form, stored["trips"]),
        "schedule": {
            "every_hours": _coerce_number(
                form.get("schedule.every_hours", stored["schedule"]["every_hours"])
            ),
        },
        "sources": {
            "google": {
                "enabled": _checkbox(form, "sources.google.enabled"),
                "use_browser_fallback": _checkbox(form, "sources.google.use_browser_fallback"),
            },
            "kiwi": {
                "enabled": _checkbox(form, "sources.kiwi.enabled"),
                "api_key": _secret_or_existing(
                    form, "sources.kiwi.api_key", stored["sources"]["kiwi"]["api_key"]
                ),
            },
            "travelpayouts": {
                "enabled": _checkbox(form, "sources.travelpayouts.enabled"),
                "token": _secret_or_existing(
                    form, "sources.travelpayouts.token", stored["sources"]["travelpayouts"]["token"]
                ),
            },
            "duffel": {
                "enabled": _checkbox(form, "sources.duffel.enabled"),
                "api_key": _secret_or_existing(
                    form, "sources.duffel.api_key", stored["sources"]["duffel"]["api_key"]
                ),
            },
            "mcp": {
                "enabled": _checkbox(form, "sources.mcp.enabled"),
                "endpoint": form.get("sources.mcp.endpoint", stored["sources"]["mcp"]["endpoint"]),
                "tool_name": form.get(
                    "sources.mcp.tool_name", stored["sources"]["mcp"]["tool_name"]
                ),
            },
        },
        "notify": {
            "channel": form.get("notify.channel", stored["notify"]["channel"]),
            "whatsapp": {
                **stored["notify"]["whatsapp"],
                "phone": form.get("notify.whatsapp.phone", stored["notify"]["whatsapp"]["phone"]),
                "callmebot_apikey": _secret_or_existing(
                    form,
                    "notify.whatsapp.callmebot_apikey",
                    stored["notify"]["whatsapp"]["callmebot_apikey"],
                ),
            },
            "ntfy": {
                "server": form.get("notify.ntfy.server", stored["notify"]["ntfy"]["server"]),
                "topic": form.get("notify.ntfy.topic", stored["notify"]["ntfy"]["topic"]),
            },
            "discord": {
                "webhook_url": _secret_or_existing(
                    form, "notify.discord.webhook_url", stored["notify"]["discord"]["webhook_url"]
                ),
            },
            "email": {
                "smtp_host": form.get(
                    "notify.email.smtp_host", stored["notify"]["email"]["smtp_host"]
                ),
                "smtp_port": _coerce_int(
                    form.get("notify.email.smtp_port", stored["notify"]["email"]["smtp_port"])
                ),
                "username": form.get(
                    "notify.email.username", stored["notify"]["email"]["username"]
                ),
                "password": _secret_or_existing(
                    form, "notify.email.password", stored["notify"]["email"]["password"]
                ),
                "to_addr": form.get("notify.email.to_addr", stored["notify"]["email"]["to_addr"]),
            },
        },
        "dashboard": {
            "top_n_fares": _coerce_int(
                form.get("dashboard.top_n_fares", stored["dashboard"]["top_n_fares"])
            ),
        },
        "ai": {
            "provider": form.get("ai.provider", stored["ai"]["provider"]),
            "ollama_base_url": form.get(
                "ai.ollama_base_url", stored["ai"]["ollama_base_url"]
            ),
            "ollama_model": form.get("ai.ollama_model", stored["ai"]["ollama_model"]),
            "llamaserver_base_url": form.get(
                "ai.llamaserver_base_url", stored["ai"]["llamaserver_base_url"]
            ),
            "llamaserver_model": form.get(
                "ai.llamaserver_model", stored["ai"]["llamaserver_model"]
            ),
            "enable_thinking": _checkbox(form, "ai.enable_thinking"),
            "searxng_base_url": form.get(
                "ai.searxng_base_url", stored["ai"]["searxng_base_url"]
            ),
            "anthropic_api_key": _secret_or_existing(
                form, "ai.anthropic_api_key", stored["ai"]["anthropic_api_key"]
            ),
            "telegram_bot_token": _secret_or_existing(
                form, "ai.telegram_bot_token", stored["ai"]["telegram_bot_token"]
            ),
            "telegram_allowed_user_id": form.get(
                "ai.telegram_allowed_user_id", stored["ai"]["telegram_allowed_user_id"]
            ),
            "discord_bot_token": _secret_or_existing(
                form, "ai.discord_bot_token", stored["ai"]["discord_bot_token"]
            ),
            "discord_allowed_user_id": form.get(
                "ai.discord_allowed_user_id", stored["ai"]["discord_allowed_user_id"]
            ),
        },
        "web": dict(stored["web"]),  # host/port/admin_password: not edited from this form
        "db": dict(stored["db"]),
    }


def _test_source(name: str, merged: dict) -> tuple[bool, str]:
    sources_raw = merged["sources"]
    factories: dict[str, tuple[Callable[[], FareSource], str]] = {
        "google": (
            lambda: GoogleFlightsSource(
                enabled=True, use_browser_fallback=sources_raw["google"]["use_browser_fallback"]
            ),
            "Google Flights",
        ),
        "kiwi": (
            lambda: KiwiSource(enabled=True, api_key=sources_raw["kiwi"]["api_key"]),
            "Kiwi",
        ),
        "travelpayouts": (
            lambda: TravelpayoutsSource(enabled=True, token=sources_raw["travelpayouts"]["token"]),
            "Travelpayouts",
        ),
        "duffel": (
            lambda: DuffelSource(enabled=True, api_key=sources_raw["duffel"]["api_key"]),
            "Duffel",
        ),
        "mcp": (
            lambda: McpSource(
                enabled=True,
                endpoint=sources_raw["mcp"]["endpoint"],
                tool_name=sources_raw["mcp"]["tool_name"],
            ),
            "MCP server",
        ),
    }
    if name not in factories:
        return False, f"Unknown source: {name}"
    build, label = factories[name]
    ok = build().health_check()
    return ok, f"{label} is reachable." if ok else "Health check failed — see logs."


@router.get("/settings")
def settings_page(request: Request, conn: SettingsConnDep):
    stored = as_dict(conn)
    flash = request.query_params.get("flash")
    flash_error = request.query_params.get("flash_error") == "1"
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "logged_in": True,
            "values": stored,
            "errors": {},
            "secrets_set": _secrets_set(conn),
            "flash": flash,
            "flash_error": flash_error,
            "source_test_result": None,
            "notify_test_result": None,
            "security_error": None,
        },
    )


@router.post("/settings")
async def settings_submit(request: Request, conn: SettingsConnDep):
    form = await request.form()
    stored = as_dict(conn)
    merged = _merge_settings_from_form(form, stored)

    if "test_source" in form:
        name = str(form["test_source"])
        ok, message = _test_source(name, merged)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "logged_in": True,
                "values": merged,
                "errors": {},
                "secrets_set": _secrets_set(conn),
                "flash": None,
                "flash_error": False,
                "source_test_result": {"name": name, "ok": ok, "message": message},
                "notify_test_result": None,
                "security_error": None,
            },
        )

    if "test_notify" in form:
        try:
            test_config = validate(merged).config.notify
            first_trip = merged["trips"][0]["trip"] if merged["trips"] else None
            route = (
                f"{first_trip['origin']} → {first_trip['destination']} (test)"
                if first_trip
                else "No trips configured (test)"
            )
            currency = first_trip["currency"] if first_trip else "USD"
            alert = Alert(
                route_key="test",
                route=route,
                price=999.0,
                currency=currency,
                reasons=["test"],
                all_time_low=999.0,
                deep_link="https://www.google.com/travel/flights",
                dashboard_url=None,
            )
            build_notifier(test_config).send(alert)
            notify_result = {"ok": True, "message": f"Test message sent via {test_config.channel}."}
        except ConfigError as exc:
            notify_result = {"ok": False, "message": "; ".join(exc.messages)}
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not raised
            notify_result = {"ok": False, "message": str(exc)}
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "logged_in": True,
                "values": merged,
                "errors": {},
                "secrets_set": _secrets_set(conn),
                "flash": None,
                "flash_error": False,
                "source_test_result": None,
                "notify_test_result": notify_result,
                "security_error": None,
            },
        )

    # default action: save
    try:
        result = validate(merged)
    except ConfigError as exc:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "logged_in": True,
                "values": merged,
                "errors": _map_errors_to_fields(exc.messages),
                "secrets_set": _secrets_set(conn),
                "flash": None,
                "flash_error": False,
                "source_test_result": None,
                "notify_test_result": None,
                "security_error": None,
            },
            status_code=400,
        )

    save_config(conn, result.config)
    return RedirectResponse("/settings?flash=Settings saved.", status_code=303)


@router.post("/settings/add-trip")
def add_trip(conn: SettingsConnDep) -> RedirectResponse:
    """Append one blank trip card. Bypasses full validate() deliberately —
    a freshly-added trip has an empty origin/destination and shouldn't be
    forced through IATA-code validation just to exist on the page; the real
    Save button still validates everything when the user is done editing it.
    """
    trips = settings_store.get(conn, "trips", [])
    trips.append(_blank_trip_entry())
    settings_store.set(conn, "trips", trips)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/remove-trip/{index}")
def remove_trip(index: int, conn: SettingsConnDep) -> RedirectResponse:
    trips = settings_store.get(conn, "trips", [])
    if 0 <= index < len(trips):
        trips.pop(index)
        settings_store.set(conn, "trips", trips)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/security")
async def change_password(request: Request, conn: SettingsConnDep):
    form = await request.form()
    current_password = str(form.get("current_password", ""))
    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))

    stored_hash = settings_store.get(conn, "web.admin_password", "")
    error = None
    if not auth.verify_password(current_password, stored_hash):
        error = "Current password is incorrect."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "New passwords don't match."

    if error:
        stored = as_dict(conn)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "logged_in": True,
                "values": stored,
                "errors": {},
                "secrets_set": _secrets_set(conn),
                "flash": None,
                "flash_error": False,
                "source_test_result": None,
                "notify_test_result": None,
                "security_error": error,
            },
            status_code=400,
        )

    settings_store.set(conn, "web.admin_password", auth.hash_password(new_password))
    # Invalidate any other existing session (e.g. a stolen cookie) by
    # rotating the signing secret, then immediately re-issue a fresh cookie
    # so the user making the change doesn't get logged out by their own
    # password change.
    auth.rotate_session_secret(conn)
    response = RedirectResponse("/settings?flash=Password changed.", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_cookie(conn),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/settings/run-now")
def run_now(conn: SettingsConnDep):
    try:
        run_poll_once(conn)
        message = "Check complete — see the Dashboard for the result."
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not raised
        message = f"Check failed: {exc}"
    from urllib.parse import quote

    return RedirectResponse(f"/settings?flash={quote(message)}", status_code=303)

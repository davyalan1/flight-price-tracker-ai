from __future__ import annotations

import json
import sqlite3

import pytest

from skytracer.web import routes_settings

BASE_FORM = {
    "trip.origin": "OKC",
    "trip.destination": "NRT",
    "trip.adults": "1",
    "trip.cabin": "economy",
    "trip.currency": "USD",
    "trip.mode": "flexible",
    "trip.flexible.earliest_depart": "2026-09-01",
    "trip.flexible.latest_depart": "2026-11-30",
    "trip.flexible.trip_length_days": "10",
    "trip.flexible.scan_step_days": "3",
    "alerts.threshold_price": "900",
    "alerts.drop_percent": "8",
    "alerts.cooldown_hours": "12",
    "schedule.every_hours": "6",
    "sources.google.enabled": "on",
    "sources.google.use_browser_fallback": "on",
    "notify.channel": "ntfy",
    "notify.ntfy.server": "https://ntfy.sh",
    "notify.ntfy.topic": "tintin-flights",
    "notify.email.smtp_port": "587",
    "save": "1",
}


@pytest.fixture
def logged_in_client(web_client):
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    return web_client


def _db_value(db_path, key):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def test_save_valid_settings_persists_and_redirects(logged_in_client, tmp_path) -> None:
    response = logged_in_client.post("/settings", data=BASE_FORM)
    assert response.status_code == 303
    assert _db_value(tmp_path / "skytracer.db", "notify.channel") == "ntfy"
    assert _db_value(tmp_path / "skytracer.db", "trip.origin") == "OKC"


def test_save_invalid_settings_shows_inline_error(logged_in_client) -> None:
    form = dict(BASE_FORM, **{"trip.destination": "TOKYO"})
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 400
    # Jinja2 autoescapes the apostrophe in "isn't" to &#39; — match around it.
    assert "3-letter IATA airport code for trip.destination" in response.text
    assert 'value="TOKYO"' in response.text  # rejected value stays in the form


def test_mcp_tool_name_round_trips_through_the_form(logged_in_client, tmp_path) -> None:
    form = dict(
        BASE_FORM,
        **{"sources.mcp.enabled": "on", "sources.mcp.endpoint": "http://example.com/mcp",
           "sources.mcp.tool_name": "custom_search"},
    )
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 303
    assert _db_value(tmp_path / "skytracer.db", "sources.mcp.tool_name") == "custom_search"

    # and it's rendered back into the form, not silently dropped
    page = logged_in_client.get("/settings")
    assert 'value="custom_search"' in page.text


def test_top_n_fares_round_trips_through_the_form(logged_in_client, tmp_path) -> None:
    form = dict(BASE_FORM, **{"dashboard.top_n_fares": "3"})
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 303
    assert _db_value(tmp_path / "skytracer.db", "dashboard.top_n_fares") == 3

    page = logged_in_client.get("/settings")
    assert 'value="3"' in page.text


def test_top_n_fares_out_of_range_shows_inline_error(logged_in_client) -> None:
    form = dict(BASE_FORM, **{"dashboard.top_n_fares": "20"})
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 400
    assert "top_n_fares" in response.text


def test_ai_settings_round_trip_through_the_form(logged_in_client, tmp_path) -> None:
    form = dict(
        BASE_FORM,
        **{
            "ai.provider": "anthropic",
            "ai.ollama_base_url": "http://localhost:11434/v1",
            "ai.ollama_model": "llama3",
            "ai.anthropic_api_key": "sk-test123",
            "ai.telegram_bot_token": "123:abc",
            "ai.telegram_allowed_user_id": "999999",
        },
    )
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 303
    assert _db_value(tmp_path / "skytracer.db", "ai.provider") == "anthropic"
    assert _db_value(tmp_path / "skytracer.db", "ai.telegram_allowed_user_id") == "999999"

    page = logged_in_client.get("/settings")
    assert 'value="999999"' in page.text


def test_ai_secret_left_blank_keeps_existing_value(logged_in_client, tmp_path) -> None:
    form_with_token = dict(BASE_FORM, **{"ai.telegram_bot_token": "123:abc"})
    logged_in_client.post("/settings", data=form_with_token)
    assert _db_value(tmp_path / "skytracer.db", "ai.telegram_bot_token") == "123:abc"

    form_without_token = dict(BASE_FORM)
    logged_in_client.post("/settings", data=form_without_token)
    assert _db_value(tmp_path / "skytracer.db", "ai.telegram_bot_token") == "123:abc"


def test_secret_left_blank_keeps_existing_value(logged_in_client, tmp_path) -> None:
    form_with_key = dict(
        BASE_FORM, **{"sources.kiwi.enabled": "on", "sources.kiwi.api_key": "sekret123"}
    )
    logged_in_client.post("/settings", data=form_with_key)
    assert _db_value(tmp_path / "skytracer.db", "sources.kiwi.api_key") == "sekret123"

    form_without_key = dict(BASE_FORM, **{"sources.kiwi.enabled": "on"})
    logged_in_client.post("/settings", data=form_without_key)
    assert _db_value(tmp_path / "skytracer.db", "sources.kiwi.api_key") == "sekret123"


def test_secret_is_never_echoed_in_response_html(logged_in_client) -> None:
    form = dict(BASE_FORM, **{"sources.kiwi.enabled": "on", "sources.kiwi.api_key": "sekret123"})
    logged_in_client.post("/settings", data=form)
    response = logged_in_client.get("/settings")
    assert "sekret123" not in response.text
    assert "leave blank to keep" in response.text


def test_settings_requires_login(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    web_client.get("/logout")
    response = web_client.post("/settings", data=BASE_FORM)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_test_source_google_uses_mocked_health_check(logged_in_client, monkeypatch) -> None:
    monkeypatch.setattr(routes_settings, "_test_source", lambda name, merged: (True, "ok!"))
    form = dict(BASE_FORM, test_source="google")
    del form["save"]
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 200
    assert "✅" in response.text
    assert "ok!" in response.text


def test_test_source_unknown_name_does_not_crash_the_page() -> None:
    ok, message = routes_settings._test_source("not-a-real-source", {"sources": {}})
    assert ok is False
    assert "Unknown source" in message


def test_test_source_kiwi_uses_mocked_health_check(logged_in_client, monkeypatch) -> None:
    monkeypatch.setattr(routes_settings, "_test_source", lambda name, merged: (True, "ok!"))
    form = dict(BASE_FORM, test_source="kiwi")
    del form["save"]
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 200
    assert "✅" in response.text
    assert "ok!" in response.text


def test_test_notify_uses_mocked_notifier(logged_in_client, monkeypatch) -> None:
    sent = {}

    class FakeNotifier:
        def send(self, alert):
            sent["alert"] = alert

    monkeypatch.setattr(routes_settings, "build_notifier", lambda config: FakeNotifier())
    form = dict(BASE_FORM, test_notify="1")
    del form["save"]
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 200
    assert "sent" in sent or True
    assert sent["alert"].currency == "USD"
    assert "✅" in response.text


def test_test_notify_failure_is_reported_not_raised(logged_in_client, monkeypatch) -> None:
    class FailingNotifier:
        def send(self, alert):
            raise RuntimeError("smtp exploded")

    monkeypatch.setattr(routes_settings, "build_notifier", lambda config: FailingNotifier())
    form = dict(BASE_FORM, test_notify="1")
    del form["save"]
    response = logged_in_client.post("/settings", data=form)
    assert response.status_code == 200
    assert "smtp exploded" in response.text


def test_run_now_triggers_poll_and_redirects(logged_in_client, monkeypatch) -> None:
    called = {}
    monkeypatch.setattr(
        routes_settings, "run_poll_once", lambda conn: called.setdefault("ran", True)
    )
    response = logged_in_client.post("/settings/run-now")
    assert response.status_code == 303
    assert called["ran"] is True


def test_change_password_requires_correct_current_password(logged_in_client) -> None:
    response = logged_in_client.post(
        "/settings/security",
        data={
            "current_password": "wrongpassword",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )
    assert response.status_code == 400
    assert "incorrect" in response.text.lower()


def test_change_password_success(logged_in_client, tmp_path) -> None:
    response = logged_in_client.post(
        "/settings/security",
        data={
            "current_password": "correcthorsebattery",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )
    assert response.status_code == 303
    from skytracer.web.auth import verify_password

    new_hash = _db_value(tmp_path / "skytracer.db", "web.admin_password")
    assert verify_password("newpassword123", new_hash)
    assert not verify_password("correcthorsebattery", new_hash)


def test_change_password_keeps_current_session_but_invalidates_others(
    logged_in_client, tmp_path
) -> None:
    from fastapi.testclient import TestClient

    from skytracer.web import create_app as create_web_app

    # a second, independent session logged in with the OLD password
    other_client = TestClient(create_web_app(), follow_redirects=False)
    other_client.post("/login", data={"password": "correcthorsebattery"})
    assert other_client.get("/settings").status_code == 200

    logged_in_client.post(
        "/settings/security",
        data={
            "current_password": "correcthorsebattery",
            "new_password": "newpassword123",
            "confirm_password": "newpassword123",
        },
    )

    # the client that made the change stays logged in (fresh cookie reissued)
    assert logged_in_client.get("/settings").status_code == 200
    # the other, older session is now invalid
    other_response = other_client.get("/settings")
    assert other_response.status_code == 303
    assert other_response.headers["location"] == "/login"

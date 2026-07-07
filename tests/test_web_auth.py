from __future__ import annotations

from fastapi.testclient import TestClient

from skytracer.web import auth
from skytracer.web import create_app as create_web_app


def test_dashboard_accessible_without_login(web_client) -> None:
    response = web_client.get("/")
    assert response.status_code == 200


def test_settings_redirects_to_setup_on_first_run(web_client) -> None:
    response = web_client.get("/settings")
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


def test_setup_creates_password_and_logs_in(web_client) -> None:
    response = web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert auth.SESSION_COOKIE_NAME in response.cookies


def test_setup_rejects_short_password(web_client) -> None:
    response = web_client.post("/setup", data={"password": "short", "confirm": "short"})
    assert response.status_code == 400


def test_setup_rejects_mismatched_confirmation(web_client) -> None:
    response = web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "somethingelse"}
    )
    assert response.status_code == 400


def test_setup_redirects_to_login_once_already_configured(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    response = web_client.get("/setup")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_settings_requires_login_after_setup(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    fresh_client = TestClient(create_web_app(), follow_redirects=False)
    response = fresh_client.get("/settings")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_with_wrong_password_fails(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    response = web_client.post("/login", data={"password": "wrong password"})
    assert response.status_code == 401
    assert auth.SESSION_COOKIE_NAME not in response.cookies


def test_login_with_correct_password_succeeds(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    web_client.cookies.clear()
    response = web_client.post("/login", data={"password": "correcthorsebattery"})
    assert response.status_code == 303
    assert response.headers["location"] == "/settings"
    assert auth.SESSION_COOKIE_NAME in response.cookies


def test_settings_accessible_after_login(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    response = web_client.get("/settings")
    assert response.status_code == 200
    assert "Trip 1" in response.text


def test_logout_clears_session(web_client) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    web_client.get("/logout")
    response = web_client.get("/settings")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_rate_limit_blocks_after_max_attempts(web_client, monkeypatch) -> None:
    web_client.post(
        "/setup", data={"password": "correcthorsebattery", "confirm": "correcthorsebattery"}
    )
    web_client.cookies.clear()
    monkeypatch.setattr(auth, "_failed_logins", {})
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        web_client.post("/login", data={"password": "wrong"})
    response = web_client.post("/login", data={"password": "correcthorsebattery"})
    assert response.status_code == 429


def test_password_hash_roundtrip() -> None:
    hashed = auth.hash_password("hunter2222")
    assert auth.verify_password("hunter2222", hashed) is True
    assert auth.verify_password("wrongpassword", hashed) is False
    assert "hunter2222" not in hashed

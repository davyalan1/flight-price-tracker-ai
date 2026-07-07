from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

VALID_RAW_CONFIG: dict = {
    "trips": [
        {
            "trip": {
                "origin": "OKC",
                "destination": "NRT",
                "adults": 1,
                "cabin": "economy",
                "currency": "USD",
                "fixed": {"enabled": False, "depart_date": "", "return_date": ""},
                "flexible": {
                    "enabled": True,
                    "earliest_depart": "2026-09-01",
                    "latest_depart": "2026-11-30",
                    "trip_length_days": 10,
                    "scan_step_days": 3,
                },
            },
            "alerts": {
                "threshold_price": 900,
                "drop_percent": 8,
                "notify_on_new_low": True,
                "cooldown_hours": 12,
            },
        }
    ],
    "schedule": {"every_hours": 6},
    "sources": {
        "google": {"enabled": True, "use_browser_fallback": True},
        "kiwi": {"enabled": False, "api_key": ""},
        "travelpayouts": {"enabled": False, "token": ""},
        "duffel": {"enabled": False, "api_key": ""},
        "mcp": {"enabled": False, "endpoint": "", "tool_name": "search_flights"},
    },
    "notify": {
        "channel": "whatsapp",
        "whatsapp": {"provider": "callmebot", "phone": "", "callmebot_apikey": ""},
        "ntfy": {"server": "https://ntfy.sh", "topic": "tintin-flights"},
        "discord": {"webhook_url": ""},
        "email": {
            "smtp_host": "",
            "smtp_port": 587,
            "username": "",
            "password": "",
            "to_addr": "",
        },
    },
    "dashboard": {"top_n_fares": 5},
    "ai": {
        "provider": "ollama",
        "ollama_base_url": "http://localhost:11434/v1",
        "ollama_model": "llama3",
        "llamaserver_base_url": "http://localhost:11435/v1",
        "llamaserver_model": "",
        "enable_thinking": False,
        "searxng_base_url": "",
        "anthropic_api_key": "",
        "telegram_bot_token": "",
        "telegram_allowed_user_id": "",
        "discord_bot_token": "",
        "discord_allowed_user_id": "",
    },
    "web": {"host": "0.0.0.0", "port": 8087, "admin_password": ""},
    "db": {"path": "/var/lib/skytracer/skytracer.db"},
}


@pytest.fixture
def valid_raw_config() -> dict:
    return copy.deepcopy(VALID_RAW_CONFIG)


def default_ai_config(**overrides):
    from skytracer.config import AiConfig

    base = dict(VALID_RAW_CONFIG["ai"])
    base.update(overrides)
    return AiConfig(**base)


class FakeHttpResponse:
    """Minimal stand-in for httpx.Response, for notifier tests that mock
    the transport instead of hitting real webhooks/APIs."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def fake_http_response() -> type[FakeHttpResponse]:
    return FakeHttpResponse


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    """A TestClient wired to a fresh, seeded, throwaway DB — no real network
    or filesystem paths outside tmp_path.
    """
    from fastapi.testclient import TestClient

    from skytracer.web import create_app

    config_path = tmp_path / "config.toml"
    shutil.copy(REPO_ROOT / "config.example.toml", config_path)
    monkeypatch.setenv("SKYTRACER_CONFIG", str(config_path))
    monkeypatch.setenv("SKYTRACER_DB", str(tmp_path / "skytracer.db"))

    return TestClient(create_app(), follow_redirects=False)

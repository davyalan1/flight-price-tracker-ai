from __future__ import annotations

import pytest

from skytracer.config import DiscordNotifyConfig
from skytracer.models import Alert
from skytracer.notify import discord as discord_module
from skytracer.notify.discord import DiscordNotifier
from tests.conftest import FakeHttpResponse


@pytest.fixture
def alert() -> Alert:
    return Alert(
        route_key="route",
        route="OKC → NRT",
        price=1000.0,
        currency="USD",
        reasons=["new_low"],
        all_time_low=1000.0,
        deep_link="https://example.com",
        dashboard_url=None,
    )


def test_discord_posts_content_to_webhook(monkeypatch, alert: Alert) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeHttpResponse()

    monkeypatch.setattr(discord_module.httpx, "post", fake_post)
    config = DiscordNotifyConfig(webhook_url="https://discord.com/api/webhooks/1/abc")
    DiscordNotifier(config).send(alert)

    assert captured["url"] == "https://discord.com/api/webhooks/1/abc"
    assert "OKC → NRT" in captured["json"]["content"]


def test_discord_raises_when_not_configured(alert: Alert) -> None:
    config = DiscordNotifyConfig(webhook_url="")
    with pytest.raises(RuntimeError, match="webhook_url"):
        DiscordNotifier(config).send(alert)


def test_discord_raises_on_http_error(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(discord_module.httpx, "post", lambda *a, **k: FakeHttpResponse(404))
    config = DiscordNotifyConfig(webhook_url="https://discord.com/api/webhooks/1/abc")
    with pytest.raises(RuntimeError, match="HTTP 404"):
        DiscordNotifier(config).send(alert)


def test_discord_http_error_does_not_leak_webhook_url(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(discord_module.httpx, "post", lambda *a, **k: FakeHttpResponse(400))
    secret_webhook = "https://discord.com/api/webhooks/123456/super-secret-token"
    config = DiscordNotifyConfig(webhook_url=secret_webhook)
    with pytest.raises(RuntimeError) as exc_info:
        DiscordNotifier(config).send(alert)
    assert secret_webhook not in str(exc_info.value)

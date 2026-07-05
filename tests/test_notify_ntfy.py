from __future__ import annotations

import pytest

from skytracer.config import NtfyNotifyConfig
from skytracer.models import Alert
from skytracer.notify import ntfy as ntfy_module
from skytracer.notify.ntfy import NtfyNotifier
from tests.conftest import FakeHttpResponse


@pytest.fixture
def alert() -> Alert:
    return Alert(
        route_key="route",
        route="OKC → NRT",
        price=1000.0,
        currency="USD",
        reasons=["threshold"],
        all_time_low=1000.0,
        deep_link="https://example.com",
        dashboard_url=None,
    )


def test_ntfy_posts_to_server_topic_url(monkeypatch, alert: Alert) -> None:
    captured = {}

    def fake_post(url, content=None, headers=None, timeout=None):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        return FakeHttpResponse()

    monkeypatch.setattr(ntfy_module.httpx, "post", fake_post)
    config = NtfyNotifyConfig(server="https://ntfy.sh", topic="tintin-flights")
    NtfyNotifier(config).send(alert)

    assert captured["url"] == "https://ntfy.sh/tintin-flights"
    assert b"USD 1000.00" in captured["content"]
    assert captured["headers"]["Title"] == "OKC -> NRT"


def test_ntfy_strips_trailing_slash_from_server(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(ntfy_module.httpx, "post", lambda *a, **k: FakeHttpResponse())
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return FakeHttpResponse()

    monkeypatch.setattr(ntfy_module.httpx, "post", fake_post)
    config = NtfyNotifyConfig(server="https://ntfy.sh/", topic="tintin-flights")
    NtfyNotifier(config).send(alert)
    assert captured["url"] == "https://ntfy.sh/tintin-flights"


def test_ntfy_raises_on_http_error(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(ntfy_module.httpx, "post", lambda *a, **k: FakeHttpResponse(500))
    config = NtfyNotifyConfig(server="https://ntfy.sh", topic="topic")
    with pytest.raises(RuntimeError, match="HTTP 500"):
        NtfyNotifier(config).send(alert)

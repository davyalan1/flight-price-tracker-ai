from __future__ import annotations

import pytest

from skytracer.config import WhatsappNotifyConfig
from skytracer.models import Alert
from skytracer.notify import whatsapp as whatsapp_module
from skytracer.notify.whatsapp import WhatsappNotifier
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


def test_callmebot_sends_get_with_expected_params(monkeypatch, alert: Alert) -> None:
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeHttpResponse()

    monkeypatch.setattr(whatsapp_module.httpx, "get", fake_get)
    config = WhatsappNotifyConfig(
        provider="callmebot", phone="+14055551234", callmebot_apikey="key123"
    )
    WhatsappNotifier(config).send(alert)

    assert captured["url"] == whatsapp_module.CALLMEBOT_URL
    assert captured["params"]["phone"] == "+14055551234"
    assert captured["params"]["apikey"] == "key123"
    assert "OKC → NRT" in captured["params"]["text"]


def test_callmebot_raises_when_not_configured(alert: Alert) -> None:
    config = WhatsappNotifyConfig(provider="callmebot", phone="", callmebot_apikey="")
    with pytest.raises(RuntimeError, match="missing phone"):
        WhatsappNotifier(config).send(alert)


def test_callmebot_raises_on_http_error(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(whatsapp_module.httpx, "get", lambda *a, **k: FakeHttpResponse(500))
    config = WhatsappNotifyConfig(provider="callmebot", phone="+1", callmebot_apikey="key")
    with pytest.raises(RuntimeError, match="HTTP 500"):
        WhatsappNotifier(config).send(alert)


def test_callmebot_http_error_does_not_leak_apikey(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(whatsapp_module.httpx, "get", lambda *a, **k: FakeHttpResponse(400))
    config = WhatsappNotifyConfig(
        provider="callmebot", phone="+1", callmebot_apikey="super-secret-key"
    )
    with pytest.raises(RuntimeError) as exc_info:
        WhatsappNotifier(config).send(alert)
    assert "super-secret-key" not in str(exc_info.value)


def test_cloud_api_sends_template_post(monkeypatch, alert: Alert) -> None:
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeHttpResponse()

    monkeypatch.setattr(whatsapp_module.httpx, "post", fake_post)
    config = WhatsappNotifyConfig(
        provider="cloud_api",
        phone="+14055551234",
        callmebot_apikey="",
        cloud_api_phone_number_id="12345",
        cloud_api_access_token="token",
    )
    WhatsappNotifier(config).send(alert)

    assert "12345" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["json"]["type"] == "template"


def test_cloud_api_raises_when_not_configured(alert: Alert) -> None:
    config = WhatsappNotifyConfig(provider="cloud_api", phone="+1", callmebot_apikey="")
    with pytest.raises(RuntimeError, match="cloud_api"):
        WhatsappNotifier(config).send(alert)


def test_twilio_sends_basic_auth_post(monkeypatch, alert: Alert) -> None:
    captured = {}

    def fake_post(url, data=None, auth=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        return FakeHttpResponse()

    monkeypatch.setattr(whatsapp_module.httpx, "post", fake_post)
    config = WhatsappNotifyConfig(
        provider="twilio",
        phone="+14055551234",
        callmebot_apikey="",
        twilio_account_sid="SID",
        twilio_auth_token="TOKEN",
        twilio_from_number="+18005551234",
    )
    WhatsappNotifier(config).send(alert)

    assert "SID" in captured["url"]
    assert captured["auth"] == ("SID", "TOKEN")
    assert captured["data"]["To"] == "whatsapp:+14055551234"


def test_twilio_raises_when_not_configured(alert: Alert) -> None:
    config = WhatsappNotifyConfig(provider="twilio", phone="+1", callmebot_apikey="")
    with pytest.raises(RuntimeError, match="twilio"):
        WhatsappNotifier(config).send(alert)


def test_unknown_provider_raises(alert: Alert) -> None:
    config = WhatsappNotifyConfig(provider="carrier_pigeon", phone="+1", callmebot_apikey="key")
    with pytest.raises(ValueError, match="Unknown whatsapp provider"):
        WhatsappNotifier(config).send(alert)

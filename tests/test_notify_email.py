from __future__ import annotations

import pytest

from skytracer.config import EmailNotifyConfig
from skytracer.models import Alert
from skytracer.notify import email as email_module
from skytracer.notify.email import EmailNotifier


@pytest.fixture
def alert() -> Alert:
    return Alert(
        route_key="route",
        route="OKC → NRT",
        price=1000.0,
        currency="USD",
        reasons=["drop"],
        all_time_low=1000.0,
        deep_link="https://example.com",
        dashboard_url=None,
    )


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args = None
        self.sent_message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.starttls_called = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent_message = message


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    FakeSMTP.instances.clear()
    yield
    FakeSMTP.instances.clear()


def test_email_sends_via_smtp_with_login(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    config = EmailNotifyConfig(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="secret",
        to_addr="tintin@example.com",
    )
    EmailNotifier(config).send(alert)

    smtp = FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.starttls_called is True
    assert smtp.login_args == ("user@example.com", "secret")
    assert smtp.sent_message["To"] == "tintin@example.com"
    assert "OKC → NRT" in smtp.sent_message["Subject"]


def test_email_skips_login_when_no_username(monkeypatch, alert: Alert) -> None:
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    config = EmailNotifyConfig(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="",
        password="",
        to_addr="tintin@example.com",
    )
    EmailNotifier(config).send(alert)

    smtp = FakeSMTP.instances[0]
    assert smtp.login_args is None


def test_email_raises_when_not_configured(alert: Alert) -> None:
    config = EmailNotifyConfig(
        smtp_host="", smtp_port=587, username="", password="", to_addr=""
    )
    with pytest.raises(RuntimeError, match="smtp_host"):
        EmailNotifier(config).send(alert)

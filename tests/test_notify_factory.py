from __future__ import annotations

import pytest

from skytracer.config import (
    DiscordNotifyConfig,
    EmailNotifyConfig,
    NotifyConfig,
    NtfyNotifyConfig,
    WhatsappNotifyConfig,
)
from skytracer.notify import build_notifier
from skytracer.notify.discord import DiscordNotifier
from skytracer.notify.email import EmailNotifier
from skytracer.notify.ntfy import NtfyNotifier
from skytracer.notify.whatsapp import WhatsappNotifier


def _notify_config(channel: str) -> NotifyConfig:
    return NotifyConfig(
        channel=channel,
        whatsapp=WhatsappNotifyConfig(provider="callmebot", phone="", callmebot_apikey=""),
        ntfy=NtfyNotifyConfig(server="https://ntfy.sh", topic="t"),
        discord=DiscordNotifyConfig(webhook_url=""),
        email=EmailNotifyConfig(smtp_host="", smtp_port=587, username="", password="", to_addr=""),
    )


@pytest.mark.parametrize(
    ("channel", "expected_type"),
    [
        ("whatsapp", WhatsappNotifier),
        ("ntfy", NtfyNotifier),
        ("discord", DiscordNotifier),
        ("email", EmailNotifier),
    ],
)
def test_build_notifier_returns_expected_type(channel: str, expected_type: type) -> None:
    notifier = build_notifier(_notify_config(channel))
    assert isinstance(notifier, expected_type)


def test_build_notifier_unknown_channel_raises() -> None:
    with pytest.raises(ValueError, match="Unknown notify channel"):
        build_notifier(_notify_config("carrier_pigeon"))

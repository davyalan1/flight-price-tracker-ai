"""Notification channels. Each Notifier renders an Alert to text (via
rendering.render_alert_message) and ships it over its own transport.
`send_text` bypasses the Alert/rendering pipeline for system messages that
aren't a fare alert (currently just the watchdog's "tracker is broken").
"""

from __future__ import annotations

from typing import Protocol

from skytracer.config import NotifyConfig
from skytracer.models import Alert
from skytracer.notify.discord import DiscordNotifier
from skytracer.notify.email import EmailNotifier
from skytracer.notify.ntfy import NtfyNotifier
from skytracer.notify.whatsapp import WhatsappNotifier


class Notifier(Protocol):
    def send(self, alert: Alert) -> None: ...
    def send_text(self, text: str) -> None: ...


def build_notifier(config: NotifyConfig) -> Notifier:
    if config.channel == "whatsapp":
        return WhatsappNotifier(config.whatsapp)
    if config.channel == "ntfy":
        return NtfyNotifier(config.ntfy)
    if config.channel == "discord":
        return DiscordNotifier(config.discord)
    if config.channel == "email":
        return EmailNotifier(config.email)
    raise ValueError(f"Unknown notify channel: {config.channel!r}")

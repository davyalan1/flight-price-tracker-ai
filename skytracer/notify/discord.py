from __future__ import annotations

from dataclasses import dataclass

import httpx

from skytracer.config import DiscordNotifyConfig
from skytracer.models import Alert
from skytracer.notify._http import check_response
from skytracer.notify.rendering import render_alert_message

TIMEOUT_SECONDS = 15.0


@dataclass
class DiscordNotifier:
    config: DiscordNotifyConfig

    def send(self, alert: Alert) -> None:
        self.send_text(render_alert_message(alert))

    def send_text(self, text: str) -> None:
        if not self.config.webhook_url:
            raise RuntimeError("notify.discord is missing webhook_url")
        response = httpx.post(
            self.config.webhook_url, json={"content": text}, timeout=TIMEOUT_SECONDS
        )
        check_response(response, "discord")

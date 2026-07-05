from __future__ import annotations

from dataclasses import dataclass

import httpx

from skytracer.config import NtfyNotifyConfig
from skytracer.models import Alert
from skytracer.notify._http import check_response
from skytracer.notify.rendering import render_alert_message

TIMEOUT_SECONDS = 15.0


@dataclass
class NtfyNotifier:
    config: NtfyNotifyConfig

    def send(self, alert: Alert) -> None:
        # ntfy's Title header must be ASCII-safe; the route string uses "→".
        ascii_route = alert.route.replace("→", "->")
        title = ascii_route.encode("ascii", "ignore").decode() or "Skytracer"
        self._post(render_alert_message(alert), title)

    def send_text(self, text: str) -> None:
        self._post(text, "Skytracer")

    def _post(self, message: str, title: str) -> None:
        url = f"{self.config.server.rstrip('/')}/{self.config.topic}"
        response = httpx.post(
            url, content=message.encode("utf-8"), headers={"Title": title}, timeout=TIMEOUT_SECONDS
        )
        check_response(response, "ntfy")

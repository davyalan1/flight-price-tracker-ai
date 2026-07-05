"""WhatsApp notifications. CallMeBot is the shipped default: free, and the
end user self-onboards entirely from their own phone (see the Settings page
copy in Phase 5). cloud_api and twilio are upgrade paths behind the same
provider switch — both require a Meta-pre-approved message template because
a price alert is a business-initiated message outside the 24h customer
session window; neither is the default.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from skytracer.config import WhatsappNotifyConfig
from skytracer.models import Alert
from skytracer.notify._http import check_response
from skytracer.notify.rendering import render_alert_message

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
TIMEOUT_SECONDS = 15.0


@dataclass
class WhatsappNotifier:
    config: WhatsappNotifyConfig

    def send(self, alert: Alert) -> None:
        self.send_text(render_alert_message(alert))

    def send_text(self, text: str) -> None:
        message = text
        if self.config.provider == "callmebot":
            self._send_callmebot(message)
        elif self.config.provider == "cloud_api":
            self._send_cloud_api(message)
        elif self.config.provider == "twilio":
            self._send_twilio(message)
        else:
            raise ValueError(f"Unknown whatsapp provider: {self.config.provider!r}")

    def _send_callmebot(self, message: str) -> None:
        if not (self.config.phone and self.config.callmebot_apikey):
            raise RuntimeError("notify.whatsapp (callmebot) is missing phone/callmebot_apikey")
        params = {
            "phone": self.config.phone,
            "text": message,
            "apikey": self.config.callmebot_apikey,
        }
        response = httpx.get(CALLMEBOT_URL, params=params, timeout=TIMEOUT_SECONDS)
        check_response(response, "whatsapp (callmebot)")

    def _send_cloud_api(self, message: str) -> None:
        if not (self.config.cloud_api_phone_number_id and self.config.cloud_api_access_token):
            raise RuntimeError(
                "notify.whatsapp (cloud_api) is missing cloud_api_phone_number_id/"
                "cloud_api_access_token"
            )
        url = (
            "https://graph.facebook.com/v18.0/"
            f"{self.config.cloud_api_phone_number_id}/messages"
        )
        headers = {"Authorization": f"Bearer {self.config.cloud_api_access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": self.config.phone,
            "type": "template",
            "template": {
                "name": self.config.cloud_api_template_name or "price_alert",
                "language": {"code": "en_US"},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": message}]}
                ],
            },
        }
        response = httpx.post(url, headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
        check_response(response, "whatsapp (cloud_api)")

    def _send_twilio(self, message: str) -> None:
        if not (
            self.config.twilio_account_sid
            and self.config.twilio_auth_token
            and self.config.twilio_from_number
        ):
            raise RuntimeError(
                "notify.whatsapp (twilio) is missing twilio_account_sid/twilio_auth_token/"
                "twilio_from_number"
            )
        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{self.config.twilio_account_sid}/Messages.json"
        )
        data = {
            "From": f"whatsapp:{self.config.twilio_from_number}",
            "To": f"whatsapp:{self.config.phone}",
            "Body": message,
        }
        response = httpx.post(
            url,
            data=data,
            auth=(self.config.twilio_account_sid, self.config.twilio_auth_token),
            timeout=TIMEOUT_SECONDS,
        )
        check_response(response, "whatsapp (twilio)")

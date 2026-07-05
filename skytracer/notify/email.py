from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from skytracer.config import EmailNotifyConfig
from skytracer.models import Alert
from skytracer.notify.rendering import render_alert_message

TIMEOUT_SECONDS = 15.0


@dataclass
class EmailNotifier:
    config: EmailNotifyConfig

    def send(self, alert: Alert) -> None:
        subject = f"Skytracer: {alert.route} — {alert.currency} {alert.price:.2f}"
        self._send(subject, render_alert_message(alert))

    def send_text(self, text: str) -> None:
        self._send("Skytracer", text)

    def _send(self, subject: str, body: str) -> None:
        if not (self.config.smtp_host and self.config.to_addr):
            raise RuntimeError("notify.email is missing smtp_host/to_addr")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.username or "skytracer@localhost"
        message["To"] = self.config.to_addr
        message.set_content(body)

        smtp_args = (self.config.smtp_host, self.config.smtp_port)
        with smtplib.SMTP(*smtp_args, timeout=TIMEOUT_SECONDS) as smtp:
            smtp.starttls()
            if self.config.username:
                smtp.login(self.config.username, self.config.password)
            smtp.send_message(message)

"""Alert -> message text. Pure and shared by every channel so the wording
stays consistent; kept short and emoji-light so it reads cleanly on a phone.
"""

from __future__ import annotations

from skytracer.models import Alert


def render_alert_message(alert: Alert) -> str:
    reason_text = ", ".join(r.replace("_", " ") for r in alert.reasons)
    lines = [
        alert.route,
        f"{alert.currency} {alert.price:.2f} — {reason_text}",
        f"All-time low: {alert.currency} {alert.all_time_low:.2f}",
    ]
    if alert.deep_link:
        lines.append(alert.deep_link)
    return "\n".join(lines)

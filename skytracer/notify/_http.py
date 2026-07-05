"""Shared HTTP response handling for notifier transports.

Deliberately does NOT use httpx.Response.raise_for_status(): its exception
message embeds the full request URL, which for CallMeBot (apikey is a query
param) and Discord (the webhook URL *is* the secret) would leak credentials
into ERROR-level logs the moment a request fails — exactly what spec §13's
"no secrets in code, logs, or settings-echo responses" rules out.
"""

from __future__ import annotations

import httpx


def check_response(response: httpx.Response, label: str) -> None:
    if response.status_code >= 400:
        raise RuntimeError(f"{label}: HTTP {response.status_code}")

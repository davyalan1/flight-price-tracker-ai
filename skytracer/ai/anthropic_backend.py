"""Cloud LLM backend via Anthropic's Messages API — plain httpx, same
convention as every other REST API adapter in this app, no vendor SDK
needed for one JSON POST.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024


@dataclass
class AnthropicBackend:
    api_key: str

    def reply(self, system: str, question: str) -> str:
        response = httpx.post(
            API_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": [{"role": "user", "content": question}],
            },
            timeout=60,
        )
        response.raise_for_status()
        blocks = response.json()["content"]
        return "".join(block["text"] for block in blocks if block["type"] == "text")

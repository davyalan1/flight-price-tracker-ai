"""Local LLM backend via Ollama's OpenAI-compatible /chat/completions
endpoint — plain httpx, same convention as every other REST API adapter in
this app (see sources/duffel.py, sources/kiwi.py), no vendor SDK needed for
one JSON POST.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class OllamaBackend:
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3"

    def reply(self, system: str, question: str) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or ""

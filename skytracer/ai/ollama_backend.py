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
    thinking: bool = False

    def reply(self, system: str, question: str) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": question},
                ],
                # Ollama's own toggle for hybrid-reasoning models (distinct
                # from llama-server's chat_template_kwargs shape below).
                "think": self.thinking,
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not content:
            # Seen for real against a misbehaving Ollama server: 200 OK,
            # finish_reason null, empty content, garbage in a "reasoning"
            # field — an empty string here would otherwise silently reach
            # a bot's send-message call.
            raise RuntimeError("Ollama returned an empty response")
        return content

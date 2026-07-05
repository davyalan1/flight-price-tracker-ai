"""Local LLM backend via llama.cpp's llama-server, OpenAI-compatible
/chat/completions endpoint — same shape as OllamaBackend, but the
thinking-mode toggle uses a different request field (chat_template_kwargs),
so it gets its own small adapter rather than a shared "local" backend with
provider-specific conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class LlamaServerBackend:
    base_url: str = "http://localhost:11435/v1"
    model: str = "qwen3.5"
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
                "chat_template_kwargs": {"enable_thinking": self.thinking},
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not content:
            raise RuntimeError("llama-server returned an empty response")
        return content

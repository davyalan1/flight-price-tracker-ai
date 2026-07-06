"""Local LLM backend via llama.cpp's llama-server, OpenAI-compatible
/chat/completions endpoint — same shape as OllamaBackend, but the
thinking-mode toggle uses a different request field (chat_template_kwargs),
so it gets its own small adapter rather than a shared "local" backend with
provider-specific conditionals.
"""

from __future__ import annotations

from dataclasses import dataclass

from skytracer.ai.openai_compat import chat_with_tools


@dataclass
class LlamaServerBackend:
    base_url: str = "http://localhost:11435/v1"
    model: str = "qwen3.5"
    thinking: bool = False
    searxng_base_url: str = ""

    def reply(self, system: str, question: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "chat_template_kwargs": {"enable_thinking": self.thinking},
        }
        return chat_with_tools(
            f"{self.base_url}/chat/completions", payload, self.searxng_base_url
        )

"""Local LLM backend via Ollama's OpenAI-compatible /chat/completions
endpoint — plain httpx, same convention as every other REST API adapter in
this app (see sources/duffel.py, sources/kiwi.py), no vendor SDK needed for
one JSON POST.
"""

from __future__ import annotations

from dataclasses import dataclass

from skytracer.ai.openai_compat import chat_with_tools


@dataclass
class OllamaBackend:
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3"
    thinking: bool = False
    searxng_base_url: str = ""

    def reply(self, system: str, question: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            # Ollama's own toggle for hybrid-reasoning models (distinct
            # from llama-server's chat_template_kwargs shape below).
            "think": self.thinking,
        }
        return chat_with_tools(
            f"{self.base_url}/chat/completions", payload, self.searxng_base_url
        )

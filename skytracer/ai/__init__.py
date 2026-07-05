"""LLM backends for the conversational (Telegram/Discord) chat feature.

Each backend implements the LLMBackend protocol so the local (Ollama) and
cloud (Anthropic) options are swappable via ai.provider in Settings — same
shape as the FareSource protocol pattern from Phase 6.
"""

from __future__ import annotations

from typing import Protocol


class LLMBackend(Protocol):
    def reply(self, system: str, question: str) -> str: ...

"""Builds an LLMBackend from config and answers a free-form question,
grounded in real tracked-route data. See context.py for the grounding
approach and PHASE11_CONVERSATIONAL_AI_RESEARCH.md for why.
"""

from __future__ import annotations

import sqlite3

from skytracer.ai import LLMBackend
from skytracer.ai.anthropic_backend import AnthropicBackend
from skytracer.ai.context import build_grounding_context
from skytracer.ai.ollama_backend import OllamaBackend
from skytracer.config import AiConfig

SYSTEM_PROMPT_TEMPLATE = """You are a flight-price tracking assistant. Answer the \
user's question using ONLY the data below — never invent or estimate a price, \
date, or trend that isn't explicitly given. If the data doesn't cover what \
they're asking, say so plainly instead of guessing. Keep answers short and \
conversational, like a text message.

DATA:
{context}
"""


def build_backend(config: AiConfig) -> LLMBackend:
    if config.provider == "anthropic":
        return AnthropicBackend(api_key=config.anthropic_api_key)
    return OllamaBackend(base_url=config.ollama_base_url, model=config.ollama_model)


def answer_question(conn: sqlite3.Connection, config: AiConfig, question: str) -> str:
    backend = build_backend(config)
    system = SYSTEM_PROMPT_TEMPLATE.format(context=build_grounding_context(conn))
    return backend.reply(system, question)

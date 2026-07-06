"""Builds an LLMBackend from config and answers a free-form question,
grounded in real tracked-route data. See context.py for the grounding
approach and PHASE11_CONVERSATIONAL_AI_RESEARCH.md for why.
"""

from __future__ import annotations

import sqlite3

from skytracer.ai import LLMBackend
from skytracer.ai.anthropic_backend import AnthropicBackend
from skytracer.ai.context import build_grounding_context
from skytracer.ai.llamaserver_backend import LlamaServerBackend
from skytracer.ai.ollama_backend import OllamaBackend
from skytracer.config import AiConfig

SYSTEM_PROMPT_TEMPLATE = """You are a flight-price tracking assistant. Answer the \
user's question using ONLY the flight-price data below for anything about tracked \
routes, fares, or alerts — never invent or estimate a price, date, or trend that \
isn't explicitly given. If a search_web tool is available, use it only for things \
this data doesn't cover (e.g. news, weather, general facts) — never to look up or \
second-guess a flight price. If neither the data nor a search covers what they're \
asking, say so plainly instead of guessing. Keep answers short and conversational, \
like a text message.

FLIGHT-PRICE DATA:
{context}
"""


def build_backend(config: AiConfig) -> LLMBackend:
    if config.provider == "anthropic":
        return AnthropicBackend(
            api_key=config.anthropic_api_key, searxng_base_url=config.searxng_base_url
        )
    if config.provider == "llamaserver":
        return LlamaServerBackend(
            base_url=config.llamaserver_base_url,
            model=config.llamaserver_model,
            thinking=config.enable_thinking,
            searxng_base_url=config.searxng_base_url,
        )
    return OllamaBackend(
        base_url=config.ollama_base_url,
        model=config.ollama_model,
        thinking=config.enable_thinking,
        searxng_base_url=config.searxng_base_url,
    )


def answer_question(conn: sqlite3.Connection, config: AiConfig, question: str) -> str:
    backend = build_backend(config)
    system = SYSTEM_PROMPT_TEMPLATE.format(context=build_grounding_context(conn))
    return backend.reply(system, question)

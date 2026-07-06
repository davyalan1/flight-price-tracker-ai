"""Web search via a self-hosted SearXNG instance, used as a real tool call
(not prompt-injection) — unlike the flight-price grounding data, a search
query is genuinely open-ended and can't be pre-fetched before knowing what
the model wants to look up. See PHASE12_CHAT_WIDGET_RESEARCH.md for why
this is the one place this app uses real tool-calling despite the general
"small local models are unreliable at it" caution from Phase 11.
"""

from __future__ import annotations

import httpx

TOOL_NAME = "search_web"
TOOL_DESCRIPTION = (
    "Search the web for current information not covered by the flight-price "
    "data above (e.g. news, weather, general facts). Only use this when the "
    "flight-price data alone can't answer the question."
)

# OpenAI-style function-calling schema — Ollama and llama-server both speak
# this shape over their /chat/completions endpoint.
OPENAI_TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query"}},
                "required": ["query"],
            },
        },
    }
]

# Anthropic's tool-use schema is a different shape (input_schema, not
# function.parameters) — see AnthropicBackend.
ANTHROPIC_TOOL_SCHEMA = [
    {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The search query"}},
            "required": ["query"],
        },
    }
]


def search_web(base_url: str, query: str) -> str:
    response = httpx.get(
        f"{base_url}/search", params={"q": query, "format": "json"}, timeout=15
    )
    response.raise_for_status()
    results = response.json().get("results", [])[:5]
    if not results:
        return "No search results found."
    lines = [
        f"- {r.get('title', '')}: {r.get('content', '')} ({r.get('url', '')})" for r in results
    ]
    return "\n".join(lines)

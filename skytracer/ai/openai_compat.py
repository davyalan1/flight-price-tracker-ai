"""Shared OpenAI-compatible chat-completions + tool-calling loop, used by
both OllamaBackend and LlamaServerBackend — they differ only in how each
requests "thinking" mode (see their own modules), not in how tool-calling
works, since both speak the identical OpenAI tool-call request/response
shape. Verified against a real llama-server instance before shipping (see
PHASE12_CHAT_WIDGET_RESEARCH.md).
"""

from __future__ import annotations

import json

import httpx

from skytracer.ai.tools import OPENAI_TOOL_SCHEMA, TOOL_NAME, search_web

MAX_TOOL_ROUNDS = 3


def chat_with_tools(chat_url: str, base_payload: dict, searxng_base_url: str) -> str:
    messages = list(base_payload["messages"])
    payload = dict(base_payload)
    if searxng_base_url:
        payload["tools"] = OPENAI_TOOL_SCHEMA

    for _ in range(MAX_TOOL_ROUNDS):
        payload["messages"] = messages
        response = httpx.post(chat_url, json=payload, timeout=60)
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            content = message.get("content")
            if not content:
                raise RuntimeError("backend returned an empty response")
            return content

        messages.append(message)
        for call in tool_calls:
            name = call["function"]["name"]
            if name == TOOL_NAME:
                args = json.loads(call["function"]["arguments"] or "{}")
                result = search_web(searxng_base_url, args.get("query", ""))
            else:
                result = f"Unknown tool: {name}"
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": result}
            )

    raise RuntimeError("LLM backend exceeded max tool-call rounds without answering")

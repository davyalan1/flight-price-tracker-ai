"""Cloud LLM backend via Anthropic's Messages API — plain httpx, same
convention as every other REST API adapter in this app, no vendor SDK
needed for one JSON POST. Tool-calling uses Anthropic's own request/
response shape (tool_use/tool_result content blocks), genuinely different
from the OpenAI-style tool_calls shape OllamaBackend/LlamaServerBackend
share — see openai_compat.py for that side.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from skytracer.ai.tools import ANTHROPIC_TOOL_SCHEMA, TOOL_NAME, search_web

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
MAX_TOOL_ROUNDS = 3


@dataclass
class AnthropicBackend:
    api_key: str
    searxng_base_url: str = ""

    def reply(self, system: str, question: str) -> str:
        messages = [{"role": "user", "content": question}]
        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": system,
        }
        if self.searxng_base_url:
            payload["tools"] = ANTHROPIC_TOOL_SCHEMA

        for _ in range(MAX_TOOL_ROUNDS):
            response = httpx.post(
                API_URL,
                headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
                json={**payload, "messages": messages},
                timeout=60,
            )
            response.raise_for_status()
            body = response.json()
            blocks = body["content"]

            if body.get("stop_reason") != "tool_use":
                text = "".join(b["text"] for b in blocks if b["type"] == "text")
                if not text:
                    raise RuntimeError("backend returned an empty response")
                return text

            messages.append({"role": "assistant", "content": blocks})
            tool_results = []
            for block in blocks:
                if block["type"] != "tool_use":
                    continue
                if block["name"] == TOOL_NAME:
                    result = search_web(self.searxng_base_url, block["input"].get("query", ""))
                else:
                    result = f"Unknown tool: {block['name']}"
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block["id"], "content": result}
                )
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError("LLM backend exceeded max tool-call rounds without answering")

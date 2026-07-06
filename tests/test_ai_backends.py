from __future__ import annotations

import pytest

from skytracer.ai import anthropic_backend as anthropic_module
from skytracer.ai import openai_compat as openai_compat_module
from skytracer.ai.anthropic_backend import AnthropicBackend
from skytracer.ai.llamaserver_backend import LlamaServerBackend
from skytracer.ai.ollama_backend import OllamaBackend
from tests.conftest import FakeHttpResponse


class _JsonResponse(FakeHttpResponse):
    def __init__(self, payload: dict) -> None:
        super().__init__(200)
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_ollama_backend_posts_to_chat_completions_with_base_url_and_model(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _JsonResponse({"choices": [{"message": {"content": "the reply"}}]})

    monkeypatch.setattr(openai_compat_module.httpx, "post", fake_post)

    backend = OllamaBackend(base_url="http://localhost:11434/v1", model="llama3")
    result = backend.reply("system prompt", "what's the status?")

    assert result == "the reply"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"]["model"] == "llama3"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "what's the status?"},
    ]
    assert captured["json"]["think"] is False  # thinking off by default
    assert "tools" not in captured["json"]  # no searxng_base_url configured


def test_ollama_backend_sends_think_true_when_thinking_enabled(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _JsonResponse({"choices": [{"message": {"content": "the reply"}}]})

    monkeypatch.setattr(openai_compat_module.httpx, "post", fake_post)

    OllamaBackend(thinking=True).reply("system prompt", "question")
    assert captured["json"]["think"] is True


def test_llamaserver_backend_posts_chat_template_kwargs_for_thinking(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _JsonResponse({"choices": [{"message": {"content": "the reply"}}]})

    monkeypatch.setattr(openai_compat_module.httpx, "post", fake_post)

    backend = LlamaServerBackend(
        base_url="http://localhost:11435/v1", model="qwen3.5", thinking=True
    )
    result = backend.reply("system prompt", "what's the status?")

    assert result == "the reply"
    assert captured["url"] == "http://localhost:11435/v1/chat/completions"
    assert captured["json"]["model"] == "qwen3.5"
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": True}


def test_openai_compat_backend_calls_search_tool_and_returns_final_answer(monkeypatch) -> None:
    """One round of tool-calling: the model asks for search_web, gets a
    result, then answers — verified shape-for-shape against a real
    llama-server round-trip before this test was written.
    """
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            assert json["tools"][0]["function"]["name"] == "search_web"
            return _JsonResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call1",
                                        "type": "function",
                                        "function": {
                                            "name": "search_web",
                                            "arguments": '{"query": "weather in Tokyo"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        # second round: the tool result must be in the sent messages
        assert calls[1]["messages"][-1] == {
            "role": "tool",
            "tool_call_id": "call1",
            "content": "search results here",
        }
        return _JsonResponse({"choices": [{"message": {"content": "It's sunny."}}]})

    monkeypatch.setattr(openai_compat_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        openai_compat_module, "search_web", lambda base_url, query: "search results here"
    )

    backend = OllamaBackend(searxng_base_url="http://searxng.homelab:8888")
    result = backend.reply("system prompt", "what's the weather in Tokyo?")

    assert result == "It's sunny."
    assert len(calls) == 2


def test_openai_compat_backend_gives_up_after_max_tool_rounds(monkeypatch) -> None:
    def fake_post(url, json, timeout):
        return _JsonResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "x",
                                    "type": "function",
                                    "function": {
                                        "name": "search_web",
                                        "arguments": '{"query": "loop"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(openai_compat_module.httpx, "post", fake_post)
    monkeypatch.setattr(openai_compat_module, "search_web", lambda base_url, query: "result")

    backend = OllamaBackend(searxng_base_url="http://searxng.homelab:8888")
    with pytest.raises(RuntimeError, match="max tool-call rounds"):
        backend.reply("system prompt", "question")


def test_anthropic_backend_posts_to_messages_api_with_system_and_question(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _JsonResponse(
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "the reply"}]}
        )

    monkeypatch.setattr(anthropic_module.httpx, "post", fake_post)

    backend = AnthropicBackend(api_key="sk-test")
    result = backend.reply("system prompt", "what's the status?")

    assert result == "the reply"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["json"]["system"] == "system prompt"
    assert captured["json"]["messages"] == [{"role": "user", "content": "what's the status?"}]
    assert "tools" not in captured["json"]


def test_anthropic_backend_calls_search_tool_and_returns_final_answer(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            assert json["tools"][0]["name"] == "search_web"
            return _JsonResponse(
                {
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "search_web",
                            "input": {"query": "weather"},
                        }
                    ],
                }
            )
        tool_result_block = calls[1]["messages"][-1]["content"][0]
        assert tool_result_block == {
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": "search results here",
        }
        return _JsonResponse(
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "It's sunny."}]}
        )

    monkeypatch.setattr(anthropic_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        anthropic_module, "search_web", lambda base_url, query: "search results here"
    )

    backend = AnthropicBackend(api_key="sk-test", searxng_base_url="http://searxng.homelab:8888")
    result = backend.reply("system prompt", "what's the weather?")

    assert result == "It's sunny."
    assert len(calls) == 2


@pytest.mark.parametrize(
    "backend, empty_json",
    [
        (OllamaBackend(), {"choices": [{"message": {"content": "", "reasoning": "///"}}]}),
        (LlamaServerBackend(), {"choices": [{"message": {"content": ""}}]}),
    ],
)
def test_openai_compat_backend_raises_on_empty_content(monkeypatch, backend, empty_json) -> None:
    # Seen for real against a misbehaving Ollama server: 200 OK, empty
    # content, garbage in an unused "reasoning" field. Must not silently
    # return "" — that would reach a bot's send-message call.
    monkeypatch.setattr(
        openai_compat_module.httpx, "post", lambda *a, **k: _JsonResponse(empty_json)
    )
    with pytest.raises(RuntimeError, match="empty"):
        backend.reply("system prompt", "question")


def test_anthropic_backend_raises_on_empty_content(monkeypatch) -> None:
    monkeypatch.setattr(
        anthropic_module.httpx,
        "post",
        lambda *a, **k: _JsonResponse({"stop_reason": "end_turn", "content": []}),
    )
    with pytest.raises(RuntimeError, match="empty"):
        AnthropicBackend(api_key="sk-test").reply("system prompt", "question")

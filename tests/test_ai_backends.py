from __future__ import annotations

from skytracer.ai import anthropic_backend as anthropic_module
from skytracer.ai import ollama_backend as ollama_module
from skytracer.ai.anthropic_backend import AnthropicBackend
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

    monkeypatch.setattr(ollama_module.httpx, "post", fake_post)

    backend = OllamaBackend(base_url="http://localhost:11434/v1", model="llama3")
    result = backend.reply("system prompt", "what's the status?")

    assert result == "the reply"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"]["model"] == "llama3"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "what's the status?"},
    ]


def test_anthropic_backend_posts_to_messages_api_with_system_and_question(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _JsonResponse({"content": [{"type": "text", "text": "the reply"}]})

    monkeypatch.setattr(anthropic_module.httpx, "post", fake_post)

    backend = AnthropicBackend(api_key="sk-test")
    result = backend.reply("system prompt", "what's the status?")

    assert result == "the reply"
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["json"]["system"] == "system prompt"
    assert captured["json"]["messages"] == [{"role": "user", "content": "what's the status?"}]

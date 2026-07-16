import json
from urllib.error import URLError

import pytest

from ai_tester.ollama import OllamaClient, OllamaConnectionError


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_list_models_returns_normalized_models():
    def transport(request, timeout):
        assert request.full_url == "http://ollama:11434/api/tags"
        assert timeout == 2.5
        return FakeResponse({
            "models": [
                {"name": "qwen3:8b", "size": 5_000, "modified_at": "2026-07-01T12:00:00Z"}
            ]
        })

    client = OllamaClient("http://ollama:11434/", timeout=2.5, transport=transport)

    assert client.list_models() == [{
        "name": "qwen3:8b",
        "size": 5_000,
        "modified_at": "2026-07-01T12:00:00Z",
    }]


def test_list_models_reports_connection_failure():
    def failing_transport(request, timeout):
        raise URLError("connection refused")

    client = OllamaClient("http://ollama:11434", transport=failing_transport)

    with pytest.raises(OllamaConnectionError, match="Ollama inaccessible"):
        client.list_models()


def test_generate_sends_model_and_prompt():
    captured = {}

    def transport(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return FakeResponse({"response": "GPU opérationnel", "done": True})

    client = OllamaClient("http://ollama:11434", transport=transport)

    result = client.generate("qwen3:8b", "Teste le GPU")

    assert captured == {
        "url": "http://ollama:11434/api/generate",
        "body": {"model": "qwen3:8b", "prompt": "Teste le GPU", "stream": False},
    }
    assert result == "GPU opérationnel"

import json
import socket
from urllib.error import URLError

import pytest

from ai_tester.destination_policy import DestinationPolicy, HostConfirmationRequired
from ai_tester.ollama import (
    MAX_OLLAMA_RESPONSE_BYTES,
    OllamaClient,
    OllamaConnectionError,
    OllamaResponseError,
    _NoRedirectHandler,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit=None):
        return json.dumps(self.payload).encode()


def test_default_url_targets_the_podman_host():
    assert OllamaClient().base_url == "http://host.containers.internal:11434"


def test_unknown_ollama_domain_requires_confirmation(tmp_path):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    with pytest.raises(HostConfirmationRequired) as error:
        OllamaClient(
            "http://llm.example.net:11434",
            destination_policy=policy,
            resolver=lambda host, port, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.20", port))
            ],
        )

    assert error.value.host == "llm.example.net"


def test_invalid_ollama_url_is_rejected(tmp_path):
    policy = DestinationPolicy(tmp_path / "allowed.json")

    with pytest.raises(ValueError, match="URL Ollama invalide"):
        OllamaClient("file:///etc/passwd", destination_policy=policy)


def test_ollama_redirects_are_disabled():
    handler = _NoRedirectHandler()

    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254")
        is None
    )


def test_oversized_ollama_response_is_rejected():
    class OversizedResponse(FakeResponse):
        def read(self, _limit=None):
            return b"x" * (MAX_OLLAMA_RESPONSE_BYTES + 1)

    client = OllamaClient(transport=lambda request, timeout: OversizedResponse({}))

    with pytest.raises(OllamaResponseError, match="trop volumineuse"):
        client.list_models()


def test_list_models_returns_normalized_models():
    def transport(request, *, timeout):
        assert request.full_url == "http://ollama:11434/api/tags"
        assert timeout == 2.5
        return FakeResponse(
            {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "size": 5_000,
                        "modified_at": "2026-07-01T12:00:00Z",
                    }
                ]
            }
        )

    client = OllamaClient("http://ollama:11434/", timeout=2.5, transport=transport)

    assert client.list_models() == [
        {
            "name": "qwen3:8b",
            "size": 5_000,
            "modified_at": "2026-07-01T12:00:00Z",
        }
    ]


def test_list_models_reports_connection_failure():
    def failing_transport(request, *, timeout):
        raise URLError("connection refused")

    client = OllamaClient("http://ollama:11434", transport=failing_transport)

    with pytest.raises(OllamaConnectionError, match="Ollama inaccessible"):
        client.list_models()


def test_response_read_failures_are_wrapped_as_connection_errors():
    class BrokenResponse(FakeResponse):
        def read(self, _limit=None):
            raise OSError("connection reset")

    client = OllamaClient(
        "http://ollama:11434",
        transport=lambda request, timeout: BrokenResponse({}),
    )

    with pytest.raises(OllamaConnectionError, match="Ollama inaccessible"):
        client.list_models()


def test_generate_sends_model_and_prompt():
    captured = {}

    def transport(request, *, timeout):
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

import json
import socket
import threading
from http.client import HTTPException, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError

import pytest

from ai_tester.destination_policy import HostConfirmationRequired
from ai_tester.openai_compatible import (
    MAX_OPENAI_RESPONSE_BYTES,
    OpenAIClient,
    OpenAIConnectionError,
    OpenAIResponseError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        return json.dumps(self.payload).encode()[:size]


def public_resolver(host, port, *, type):
    return [(socket.AF_INET, type, 6, "", ("93.184.216.34", port))]


def test_falsey_destination_policy_is_preserved():
    class Policy:
        def __bool__(self):
            return False

        def require_allowed(self, host, addresses):
            return None

        def add_host(self, host):
            return host

    policy = Policy()

    client = OpenAIClient(
        "https://api.example/v1",
        resolver=public_resolver,
        destination_policy=policy,
    )

    assert client.destination_policy is policy


def test_list_models_uses_configured_endpoint_and_bearer_key():
    captured = {}

    def transport(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"id": "gpt-4.1"}, {"id": "gpt-4.1-mini"}]})

    client = OpenAIClient(
        "https://api.openai.com/v1/",
        api_key="secret",
        timeout=4.0,
        transport=transport,
        resolver=public_resolver,
    )

    assert client.list_models() == ["gpt-4.1", "gpt-4.1-mini"]
    assert captured == {
        "url": "https://api.openai.com/v1/models",
        "authorization": "Bearer secret",
        "timeout": 4.0,
    }


def test_list_models_supports_endpoint_without_api_key():
    def transport(request, *, timeout):
        assert request.get_header("Authorization") is None
        return FakeResponse({"data": [{"id": "local-model"}]})

    assert OpenAIClient(
        "http://local-llm:8000/v1",
        transport=transport,
        allowed_hosts={"local-llm"},
        resolver=lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", port))
        ],
    ).list_models() == ["local-model"]


def test_chat_completion_sends_supported_parameters():
    captured = {}

    def transport(request, *, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        return FakeResponse(
            {"choices": [{"message": {"content": "Configuration valide"}}]}
        )

    result = OpenAIClient(
        "https://api.openai.com/v1",
        api_key="secret",
        transport=transport,
        resolver=public_resolver,
    ).chat(
        model="gpt-4.1-mini",
        prompt="Teste la configuration",
        system_prompt="Tu es un outil de diagnostic.",
        temperature=0.25,
        top_p=0.8,
        max_tokens=300,
    )

    assert captured == {
        "url": "https://api.openai.com/v1/chat/completions",
        "payload": {
            "model": "gpt-4.1-mini",
            "messages": [
                {"role": "system", "content": "Tu es un outil de diagnostic."},
                {"role": "user", "content": "Teste la configuration"},
            ],
            "temperature": 0.25,
            "top_p": 0.8,
            "max_tokens": 300,
            "stream": False,
        },
    }
    assert result == "Configuration valide"


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///etc/passwd",
        "https:///v1",
        "https://user:password@api.openai.com/v1",
        "https://api.openai.com/v1?target=/admin",
        "https://api.openai.com/v1#fragment",
    ],
)
def test_invalid_base_url_is_rejected(base_url):
    with pytest.raises(ValueError, match="URL OpenAI invalide"):
        OpenAIClient(base_url, resolver=public_resolver)


@pytest.mark.parametrize(
    "invalid_path",
    [
        "/v1 bad",
        "/v1\tbad",
        "/v1\nbad",
        "/v1\x00bad",
        "/v1\u2003bad",
        "/v1/café",
        "/v1/%XX",
    ],
)
def test_base_url_path_rejects_whitespace_and_control_characters(invalid_path):
    with pytest.raises(ValueError, match="URL OpenAI invalide"):
        OpenAIClient(f"https://api.openai.com{invalid_path}", resolver=public_resolver)


@pytest.mark.parametrize("control", ["\r", "\n", "\t", "\x00", "\x7f", "\x85"])
def test_api_key_rejects_control_characters(control):
    with pytest.raises(ValueError, match="API OpenAI invalide"):
        OpenAIClient(
            "https://api.openai.com/v1",
            api_key=f"secret{control}injected",
            resolver=public_resolver,
        )


def test_unlisted_outbound_host_requires_confirmation():
    with pytest.raises(HostConfirmationRequired) as error:
        OpenAIClient("https://example.com/v1", resolver=public_resolver)

    assert error.value.host == "example.com"
    assert error.value.addresses == ("93.184.216.34",)


def test_private_address_is_allowed_by_default_local_networks():
    client = OpenAIClient("http://10.0.0.1:8000/v1")

    assert client.base_url == "http://10.0.0.1:8000/v1"


def test_configured_openai_host_remains_allowed_when_dns_changes():
    client = OpenAIClient(
        "https://api.openai.com/v1",
        resolver=lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))
        ],
    )

    assert client.base_url == "https://api.openai.com/v1"


def test_environment_allowlist_permits_exact_private_host(monkeypatch):
    monkeypatch.setenv("OPENAI_ALLOWED_HOSTS", "private-llm.example")

    client = OpenAIClient(
        "http://private-llm.example:8000/v1",
        resolver=lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.10", port))
        ],
    )

    assert client.base_url == "http://private-llm.example:8000/v1"


def test_http_url_with_api_key_is_rejected():
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIClient("http://localhost:8000/v1", api_key="secret")


def test_http_without_api_key_is_allowed_for_local_development():
    client = OpenAIClient("http://127.0.0.1:8000/v1")

    assert client.base_url == "http://127.0.0.1:8000/v1"


def test_default_transport_does_not_follow_redirects():
    target_requests = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            target_requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data": []}')

        def log_message(self, *_):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header(
                "Location", f"http://127.0.0.1:{target.server_port}/target"
            )
            self.end_headers()

        def log_message(self, *_):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [
        threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        for server in (source, target)
    ]
    for thread in threads:
        thread.start()
    try:
        client = OpenAIClient(f"http://127.0.0.1:{source.server_port}/v1")
        with pytest.raises(OpenAIResponseError, match="HTTP 302"):
            client.list_models()
        assert target_requests == []
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()
        for thread in threads:
            thread.join(timeout=1)
            assert not thread.is_alive()


def test_connection_error_does_not_expose_api_key():
    def transport(request, *, timeout):
        raise URLError("connection refused")

    client = OpenAIClient(
        "https://example.invalid/v1",
        api_key="super-secret",
        transport=transport,
        allowed_hosts={"example.invalid"},
        resolver=public_resolver,
    )

    with pytest.raises(OpenAIConnectionError) as error:
        client.list_models()

    assert "super-secret" not in str(error.value)


@pytest.mark.parametrize(
    "read_error",
    [
        IncompleteRead(b"partial", 10),
        HTTPException("broken response"),
        OSError("reset"),
    ],
)
def test_response_read_transport_failures_are_wrapped(read_error):
    class BrokenResponse(FakeResponse):
        def read(self, size=-1):
            raise read_error

    client = OpenAIClient(
        "https://api.openai.com/v1",
        transport=lambda request, **kwargs: BrokenResponse({}),
        resolver=public_resolver,
    )

    with pytest.raises(OpenAIConnectionError):
        client.list_models()


def test_response_body_read_is_bounded_and_oversize_is_rejected():
    class OversizedResponse(FakeResponse):
        def __init__(self):
            super().__init__({})
            self.requested_size = None

        def read(self, size=-1):
            self.requested_size = size
            return b"x" * size

    response = OversizedResponse()
    client = OpenAIClient(
        "https://api.openai.com/v1",
        transport=lambda request, **kwargs: response,
        resolver=public_resolver,
    )

    with pytest.raises(OpenAIResponseError, match="trop volumineuse"):
        client.list_models()

    assert response.requested_size == MAX_OPENAI_RESPONSE_BYTES + 1


def test_malformed_completion_is_rejected():
    client = OpenAIClient(
        "https://example.test/v1",
        transport=lambda request, timeout: FakeResponse({"choices": []}),
        allowed_hosts={"example.test"},
        resolver=public_resolver,
    )

    with pytest.raises(OpenAIResponseError, match="complétion"):
        client.chat(model="model", prompt="hello")

import pytest

from ai_tester.destination_policy import HostConfirmationRequired
from ai_tester.web import create_app


class FakeGpuProbe:
    def status(self):
        return [{"id": "card0", "name": "AMD Radeon", "temperature_c": 51}]


class FakeOllama:
    def list_models(self):
        return [{"name": "qwen3:8b", "size": 123, "modified_at": None}]

    def generate(self, model, prompt):
        return f"{model}: {prompt}"


def client():
    app = create_app(gpu_probe=FakeGpuProbe(), ollama_client=FakeOllama())
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_identifies_ai_tester():
    response = client().get("/")

    assert response.status_code == 200
    assert b"AI Tester" in response.data
    assert b"GPU AMD et NVIDIA" in response.data
    assert b"Ollama" in response.data


def test_dashboard_exposes_openai_provider_and_generation_parameters():
    response = client().get("/")

    assert response.status_code == 200
    for field_id in (
        b'id="provider"',
        b'id="openai-base-url"',
        b'id="openai-api-key"',
        b'id="model"',
        b'id="system-prompt"',
        b'id="temperature"',
        b'id="top-p"',
        b'id="max-tokens"',
    ):
        assert field_id in response.data


def test_frontend_confirms_and_persists_unknown_openai_domain():
    response = client().get("/static/app.js")

    assert response.status_code == 200
    assert b"window.confirm" in response.data
    assert b"/api/openai/allowed-hosts" in response.data


def test_status_combines_gpu_and_ollama_diagnostics():
    response = client().get("/api/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "gpu": {"available": True, "devices": [{"id": "card0", "name": "AMD Radeon", "temperature_c": 51}]},
        "ollama": {"available": True, "models": [{"name": "qwen3:8b", "size": 123, "modified_at": None}]},
    }


def test_generate_validates_required_fields():
    response = client().post("/api/ollama/generate", json={"model": "qwen3:8b"})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Les champs model et prompt sont obligatoires"}


def test_generate_returns_ollama_response():
    response = client().post(
        "/api/ollama/generate",
        json={"model": "qwen3:8b", "prompt": "Diagnostic"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"response": "qwen3:8b: Diagnostic"}


class FakeOpenAI:
    def __init__(self, captured):
        self.captured = captured

    def list_models(self):
        return ["gpt-4.1", "gpt-4.1-mini"]

    def chat(self, **parameters):
        self.captured["chat"] = parameters
        return "Réponse OpenAI"


def openai_client(captured):
    def factory(base_url, *, api_key=""):
        captured["connection"] = {"base_url": base_url, "api_key": api_key}
        return FakeOpenAI(captured)

    app = create_app(
        gpu_probe=FakeGpuProbe(),
        ollama_client=FakeOllama(),
        openai_client_factory=factory,
    )
    app.config["TESTING"] = True
    return app.test_client()


def test_openai_models_uses_user_configuration():
    captured = {}

    response = openai_client(captured).post(
        "/api/openai/models",
        json={"base_url": "https://api.openai.com/v1", "api_key": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"models": ["gpt-4.1", "gpt-4.1-mini"]}
    assert captured["connection"] == {
        "base_url": "https://api.openai.com/v1",
        "api_key": "secret",
    }


def test_openai_chat_forwards_generation_parameters():
    captured = {}

    response = openai_client(captured).post(
        "/api/openai/chat",
        json={
            "base_url": "https://api.openai.com/v1",
            "api_key": "secret",
            "model": "gpt-4.1-mini",
            "prompt": "Diagnostic",
            "system_prompt": "Réponds brièvement.",
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 250,
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"response": "Réponse OpenAI"}
    assert captured["chat"] == {
        "model": "gpt-4.1-mini",
        "prompt": "Diagnostic",
        "system_prompt": "Réponds brièvement.",
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 250,
    }


def test_openai_chat_rejects_out_of_range_temperature():
    response = openai_client({}).post(
        "/api/openai/chat",
        json={
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1-mini",
            "prompt": "Diagnostic",
            "temperature": 3,
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "temperature doit être comprise entre 0 et 2"}


def test_openai_models_requires_base_url():
    response = openai_client({}).post("/api/openai/models", json={})

    assert response.status_code == 400
    assert response.get_json() == {"error": "Le champ base_url est obligatoire"}


@pytest.mark.parametrize("route", ["/api/openai/models", "/api/openai/chat"])
@pytest.mark.parametrize("payload", [[], "text", 42, None])
def test_openai_routes_reject_json_that_is_not_an_object(route, payload):
    response = openai_client({}).post(route, json=payload)

    assert response.status_code == 400
    assert response.get_json() == {"error": "Le corps JSON doit être un objet"}


def test_openai_route_rejects_oversized_request_body():
    response = openai_client({}).post(
        "/api/openai/models",
        json={"base_url": "https://api.openai.com/v1", "padding": "x" * 70_000},
    )

    assert response.status_code == 413


@pytest.mark.parametrize(
    ("route", "payload", "field"),
    [
        (
            "/api/openai/models",
            {"base_url": "https://api.openai.com/" + "x" * 2_100},
            "base_url",
        ),
        (
            "/api/openai/models",
            {"base_url": "https://api.openai.com/v1", "api_key": "x" * 8_193},
            "api_key",
        ),
        (
            "/api/openai/chat",
            {
                "base_url": "https://api.openai.com/v1",
                "model": "x" * 257,
                "prompt": "Diagnostic",
            },
            "model",
        ),
        (
            "/api/openai/chat",
            {
                "base_url": "https://api.openai.com/v1",
                "model": "model",
                "prompt": "x" * 32_769,
            },
            "prompt",
        ),
        (
            "/api/openai/chat",
            {
                "base_url": "https://api.openai.com/v1",
                "model": "model",
                "prompt": "Diagnostic",
                "system_prompt": "x" * 16_385,
            },
            "system_prompt",
        ),
    ],
)
def test_openai_routes_reject_oversized_fields(route, payload, field):
    response = openai_client({}).post(route, json=payload)

    assert response.status_code == 400
    assert field in response.get_json()["error"]


def test_openai_client_configuration_errors_are_bad_requests():
    response = client().post(
        "/api/openai/models",
        json={"base_url": "http://localhost:8000/v1", "api_key": "secret"},
    )

    assert response.status_code == 400
    assert "HTTPS" in response.get_json()["error"]


@pytest.mark.parametrize(
    "payload",
    [
        {"base_url": "https://api.openai.com/v1 bad"},
        {
            "base_url": "https://api.openai.com/v1",
            "api_key": "secret\r\nX-Injected: true",
        },
    ],
)
def test_openai_models_rejects_request_construction_injection(payload):
    response = client().post("/api/openai/models", json=payload)

    assert response.status_code == 400


def test_unknown_openai_domain_requests_confirmation_without_exposing_key():
    class Policy:
        def add_host(self, host):
            raise AssertionError("not called")

    def factory(base_url, *, api_key=""):
        raise HostConfirmationRequired("llm.example.net", ["203.0.113.20"])

    app = create_app(
        gpu_probe=FakeGpuProbe(),
        ollama_client=FakeOllama(),
        openai_client_factory=factory,
        destination_policy=Policy(),
    )
    response = app.test_client().post(
        "/api/openai/models",
        json={
            "base_url": "https://llm.example.net/v1",
            "api_key": "must-remain-secret",
        },
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "Le domaine « llm.example.net » doit être confirmé",
        "confirmation_required": True,
        "host": "llm.example.net",
        "addresses": ["203.0.113.20"],
    }
    assert "must-remain-secret" not in response.get_data(as_text=True)


def test_confirmed_openai_domain_is_added_to_destination_configuration():
    captured = {}

    class Policy:
        def add_host(self, host):
            captured["host"] = host
            return host

    app = create_app(
        gpu_probe=FakeGpuProbe(),
        ollama_client=FakeOllama(),
        destination_policy=Policy(),
    )
    response = app.test_client().post(
        "/api/openai/allowed-hosts",
        json={"host": "llm.example.net", "confirmed": True},
    )

    assert response.status_code == 200
    assert response.get_json() == {"allowed_host": "llm.example.net"}
    assert captured == {"host": "llm.example.net"}


def test_openai_domain_is_not_added_without_explicit_confirmation():
    class Policy:
        def add_host(self, host):
            raise AssertionError("must not be called")

    app = create_app(
        gpu_probe=FakeGpuProbe(),
        ollama_client=FakeOllama(),
        destination_policy=Policy(),
    )
    response = app.test_client().post(
        "/api/openai/allowed-hosts",
        json={"host": "llm.example.net", "confirmed": False},
    )

    assert response.status_code == 400

from collections import Counter
from inspect import signature

from flask import url_for

from ai_tester.web import create_app


class EmptyGpuProbe:
    def status(self):
        return []


class EmptyOllamaClient:
    def list_models(self):
        return []


def make_app():
    return create_app(
        gpu_probe=EmptyGpuProbe(),
        ollama_client=EmptyOllamaClient(),
    )


def test_create_app_keeps_its_dependency_injection_signature():
    parameters = signature(create_app).parameters

    assert list(parameters) == [
        "gpu_probe",
        "ollama_client",
        "ollama_client_factory",
        "openai_client_factory",
        "destination_policy",
    ]
    assert all(
        parameter.kind.name == "KEYWORD_ONLY" for parameter in parameters.values()
    )


def test_routes_and_legacy_endpoints_are_preserved_exactly_by_blueprints():
    app = make_app()

    assert set(app.blueprints) == {
        "dashboard",
        "status",
        "ollama",
        "openai",
        "destinations",
    }
    actual = Counter(
        (
            rule.rule,
            rule.endpoint,
            frozenset(rule.methods - {"HEAD", "OPTIONS"}),
        )
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "static"
    )
    expected = Counter(
        {
            ("/", "dashboard", frozenset({"GET"})): 1,
            ("/api/status", "status", frozenset({"GET"})): 1,
            ("/api/ollama/generate", "generate", frozenset({"POST"})): 1,
            ("/api/ollama/models", "ollama_models", frozenset({"POST"})): 1,
            ("/api/openai/models", "openai_models", frozenset({"POST"})): 1,
            ("/api/openai/chat", "openai_chat", frozenset({"POST"})): 1,
            (
                "/api/openai/allowed-hosts",
                "add_allowed_host",
                frozenset({"POST"}),
            ): 1,
            (
                "/api/destinations/allowed-hosts",
                "add_allowed_host",
                frozenset({"POST"}),
            ): 1,
        }
    )

    assert actual == expected


def test_legacy_endpoint_url_building_is_preserved():
    app = make_app()

    with app.test_request_context():
        assert url_for("dashboard") == "/"
        assert url_for("status") == "/api/status"
        assert url_for("generate") == "/api/ollama/generate"
        assert url_for("ollama_models") == "/api/ollama/models"
        assert url_for("openai_models") == "/api/openai/models"
        assert url_for("openai_chat") == "/api/openai/chat"
        assert url_for("add_allowed_host") == "/api/openai/allowed-hosts"

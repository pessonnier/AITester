import ai_tester.services as services_module
from ai_tester.services import AppServices


class FalseyDependency:
    def __bool__(self):
        return False


def test_app_services_preserves_explicit_dependencies(monkeypatch):
    gpu_probe = FalseyDependency()
    ollama_client = FalseyDependency()
    policy = FalseyDependency()

    services = AppServices.from_dependencies(
        gpu_probe=gpu_probe,
        ollama_client=ollama_client,
        destination_policy=policy,
    )

    assert services.gpu_probe is gpu_probe
    assert services.status_ollama_client is ollama_client
    assert services.destination_policy is policy
    assert services.make_ollama_client("http://selected:11434") is ollama_client


def test_app_services_uses_injected_factories_and_environment(monkeypatch):
    ollama_calls = []
    openai_calls = []

    def ollama_factory(base_url):
        ollama_calls.append(base_url)
        return "ollama-client"

    def openai_factory(base_url, *, api_key=""):
        openai_calls.append((base_url, api_key))
        return "openai-client"

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    services = AppServices.from_dependencies(
        ollama_client_factory=ollama_factory,
        openai_client_factory=openai_factory,
    )

    assert services.default_ollama_url == "http://ollama:11434"
    assert services.status_ollama_client is None
    assert services.make_ollama_client("http://selected:11434") == "ollama-client"
    assert (
        services.make_openai_client("https://api.example/v1", api_key="secret")
        == "openai-client"
    )
    assert ollama_calls == ["http://selected:11434"]
    assert openai_calls == [("https://api.example/v1", "secret")]


def test_default_factories_share_the_injected_destination_policy(monkeypatch):
    captured = []

    class Client:
        def __init__(self, base_url, *, destination_policy, api_key=None):
            captured.append((base_url, api_key, destination_policy))

    monkeypatch.setattr(services_module, "OllamaClient", Client)
    monkeypatch.setattr(services_module, "OpenAIClient", Client)
    policy = FalseyDependency()
    services = AppServices.from_dependencies(destination_policy=policy)

    services.make_ollama_client("http://ollama:11434")
    services.make_openai_client("https://api.example/v1", api_key="secret")

    assert captured == [
        ("http://ollama:11434", None, policy),
        ("https://api.example/v1", "secret", policy),
    ]


def test_explicit_status_client_does_not_override_the_route_factory():
    status_client = object()
    route_client = object()

    services = AppServices.from_dependencies(
        ollama_client=status_client,
        ollama_client_factory=lambda base_url: route_client,
    )

    assert services.status_ollama_client is status_client
    assert services.make_ollama_client("http://selected:11434") is route_client

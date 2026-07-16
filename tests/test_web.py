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

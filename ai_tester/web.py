"""Flask application factory for AI Tester."""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from .destination_policy import DestinationPolicy, HostConfirmationRequired
from .gpu import GpuProbeError, SystemGpuProbe
from .ollama import OllamaClient, OllamaError
from .openai_compatible import OpenAIClient, OpenAIError


MAX_REQUEST_BYTES = 64 * 1024
OPENAI_FIELD_LIMITS = {
    "base_url": 2_048,
    "api_key": 8_192,
    "model": 256,
    "prompt": 32_768,
    "system_prompt": 16_384,
}


def _oversized_field(payload: dict, *field_names: str) -> str | None:
    for name in field_names:
        value = payload.get(name)
        if isinstance(value, str) and len(value) > OPENAI_FIELD_LIMITS[name]:
            return name
    return None


def create_app(
    *,
    gpu_probe=None,
    ollama_client=None,
    openai_client_factory=None,
    destination_policy=None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    gpu = gpu_probe or SystemGpuProbe()
    ollama = ollama_client or OllamaClient(
        os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    policy = destination_policy or DestinationPolicy()
    if openai_client_factory is None:
        def make_openai_client(base_url, *, api_key=""):
            return OpenAIClient(
                base_url, api_key=api_key, destination_policy=policy
            )
    else:
        make_openai_client = openai_client_factory

    def confirmation_response(exc: HostConfirmationRequired):
        return jsonify(
            error=str(exc),
            confirmation_required=True,
            host=exc.host,
            addresses=list(exc.addresses),
        ), 403

    @app.get("/")
    def dashboard():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        result = {
            "gpu": {"available": False, "devices": []},
            "ollama": {"available": False, "models": []},
        }
        try:
            result["gpu"] = {"available": True, "devices": gpu.status()}
        except GpuProbeError as exc:
            result["gpu"]["error"] = str(exc)
        try:
            result["ollama"] = {"available": True, "models": ollama.list_models()}
        except OllamaError as exc:
            result["ollama"]["error"] = str(exc)
        return jsonify(result)

    @app.post("/api/ollama/generate")
    def generate():
        payload = request.get_json(silent=True) or {}
        model = payload.get("model")
        prompt = payload.get("prompt")
        if not isinstance(model, str) or not model.strip() or not isinstance(prompt, str) or not prompt.strip():
            return jsonify(error="Les champs model et prompt sont obligatoires"), 400
        try:
            response = ollama.generate(model.strip(), prompt.strip())
        except OllamaError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(response=response)

    @app.post("/api/openai/models")
    def openai_models():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Le corps JSON doit être un objet"), 400
        base_url = payload.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            return jsonify(error="Le champ base_url est obligatoire"), 400
        api_key = payload.get("api_key", "")
        if not isinstance(api_key, str):
            return jsonify(error="Le champ api_key doit être une chaîne"), 400
        oversized = _oversized_field(payload, "base_url", "api_key")
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            client = make_openai_client(base_url.strip(), api_key=api_key)
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            models = client.list_models()
        except OpenAIError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(models=models)

    @app.post("/api/openai/chat")
    def openai_chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Le corps JSON doit être un objet"), 400
        required = {
            "base_url": payload.get("base_url"),
            "model": payload.get("model"),
            "prompt": payload.get("prompt"),
        }
        missing = [
            name
            for name, value in required.items()
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            return jsonify(error=f"Champs obligatoires manquants : {', '.join(missing)}"), 400

        temperature = payload.get("temperature", 0.7)
        top_p = payload.get("top_p", 1.0)
        max_tokens = payload.get("max_tokens", 512)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            return jsonify(error="temperature doit être comprise entre 0 et 2"), 400
        if isinstance(top_p, bool) or not isinstance(top_p, (int, float)) or not 0 <= top_p <= 1:
            return jsonify(error="top_p doit être compris entre 0 et 1"), 400
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 1_000_000:
            return jsonify(error="max_tokens doit être un entier positif"), 400

        api_key = payload.get("api_key", "")
        system_prompt = payload.get("system_prompt", "")
        if not isinstance(api_key, str) or not isinstance(system_prompt, str):
            return jsonify(error="api_key et system_prompt doivent être des chaînes"), 400
        oversized = _oversized_field(
            payload, "base_url", "api_key", "model", "prompt", "system_prompt"
        )
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            client = make_openai_client(required["base_url"].strip(), api_key=api_key)
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            response = client.chat(
                model=required["model"].strip(),
                prompt=required["prompt"].strip(),
                system_prompt=system_prompt,
                temperature=float(temperature),
                top_p=float(top_p),
                max_tokens=max_tokens,
            )
        except OpenAIError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(response=response)

    @app.post("/api/openai/allowed-hosts")
    def add_openai_allowed_host():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Le corps JSON doit être un objet"), 400
        host = payload.get("host")
        if payload.get("confirmed") is not True:
            return jsonify(error="Une confirmation explicite est obligatoire"), 400
        if not isinstance(host, str) or not host.strip() or len(host) > 253:
            return jsonify(error="Le champ host est invalide"), 400
        try:
            allowed_host = policy.add_host(host)
        except (OSError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(allowed_host=allowed_host)

    return app


app = create_app()

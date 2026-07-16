"""Flask application factory for AI Tester."""

from __future__ import annotations

import os

from flask import Flask, jsonify, render_template, request

from .gpu import GpuProbeError, SystemGpuProbe
from .ollama import OllamaClient, OllamaError


def create_app(*, gpu_probe=None, ollama_client=None) -> Flask:
    app = Flask(__name__)
    gpu = gpu_probe or SystemGpuProbe()
    ollama = ollama_client or OllamaClient(
        os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )

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

    return app


app = create_app()

"""Ollama API routes."""

from flask import Blueprint, jsonify

from ..destination_policy import HostConfirmationRequired
from ..ollama import OllamaError
from ..services import AppServices
from .common import confirmation_response, oversized_field, require_json_object


def create_ollama_blueprint(services: AppServices) -> Blueprint:
    blueprint = Blueprint("ollama", __name__)

    def generate():
        payload = require_json_object()
        base_url = payload.get("base_url", services.default_ollama_url)
        model = payload.get("model")
        prompt = payload.get("prompt")
        if not isinstance(base_url, str) or not base_url.strip():
            return jsonify(error="Le champ base_url est obligatoire"), 400
        if (
            not isinstance(model, str)
            or not model.strip()
            or not isinstance(prompt, str)
            or not prompt.strip()
        ):
            return jsonify(error="Les champs model et prompt sont obligatoires"), 400
        oversized = oversized_field(payload, "base_url", "model", "prompt")
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            response = services.make_ollama_client(base_url.strip()).generate(
                model.strip(), prompt.strip()
            )
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except OllamaError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(response=response)

    def models():
        payload = require_json_object()
        base_url = payload.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            return jsonify(error="Le champ base_url est obligatoire"), 400
        oversized = oversized_field(payload, "base_url")
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            model_list = services.make_ollama_client(base_url.strip()).list_models()
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except OllamaError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(models=model_list)

    @blueprint.record_once
    def register_routes(state):
        state.app.add_url_rule(
            "/api/ollama/generate",
            endpoint="generate",
            view_func=generate,
            methods=["POST"],
        )
        state.app.add_url_rule(
            "/api/ollama/models",
            endpoint="ollama_models",
            view_func=models,
            methods=["POST"],
        )

    return blueprint

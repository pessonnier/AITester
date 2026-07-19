"""OpenAI-compatible API routes."""

from flask import Blueprint, jsonify

from ..destination_policy import HostConfirmationRequired
from ..openai_compatible import OpenAIError
from ..services import AppServices
from .common import confirmation_response, oversized_field, require_json_object


def create_openai_blueprint(services: AppServices) -> Blueprint:
    blueprint = Blueprint("openai", __name__)

    def models():
        payload = require_json_object()
        base_url = payload.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            return jsonify(error="Le champ base_url est obligatoire"), 400
        api_key = payload.get("api_key", "")
        if not isinstance(api_key, str):
            return jsonify(error="Le champ api_key doit être une chaîne"), 400
        oversized = oversized_field(payload, "base_url", "api_key")
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            client = services.make_openai_client(base_url.strip(), api_key=api_key)
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            model_list = client.list_models()
        except OpenAIError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(models=model_list)

    def chat():
        payload = require_json_object()
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
            return jsonify(
                error=f"Champs obligatoires manquants : {', '.join(missing)}"
            ), 400
        base_url = required["base_url"]
        model = required["model"]
        prompt = required["prompt"]
        assert isinstance(base_url, str)
        assert isinstance(model, str)
        assert isinstance(prompt, str)

        temperature = payload.get("temperature", 0.7)
        top_p = payload.get("top_p", 1.0)
        max_tokens = payload.get("max_tokens", 512)
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= temperature <= 2
        ):
            return jsonify(error="temperature doit être comprise entre 0 et 2"), 400
        if (
            isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not 0 <= top_p <= 1
        ):
            return jsonify(error="top_p doit être compris entre 0 et 1"), 400
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 1_000_000
        ):
            return jsonify(error="max_tokens doit être un entier positif"), 400

        api_key = payload.get("api_key", "")
        system_prompt = payload.get("system_prompt", "")
        if not isinstance(api_key, str) or not isinstance(system_prompt, str):
            return jsonify(
                error="api_key et system_prompt doivent être des chaînes"
            ), 400
        oversized = oversized_field(
            payload,
            "base_url",
            "api_key",
            "model",
            "prompt",
            "system_prompt",
        )
        if oversized:
            return jsonify(error=f"Le champ {oversized} est trop long"), 400
        try:
            client = services.make_openai_client(
                base_url.strip(),
                api_key=api_key,
            )
        except HostConfirmationRequired as exc:
            return confirmation_response(exc)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        try:
            response = client.chat(
                model=model.strip(),
                prompt=prompt.strip(),
                system_prompt=system_prompt,
                temperature=float(temperature),
                top_p=float(top_p),
                max_tokens=max_tokens,
            )
        except OpenAIError as exc:
            return jsonify(error=str(exc)), 502
        return jsonify(response=response)

    @blueprint.record_once
    def register_routes(state):
        state.app.add_url_rule(
            "/api/openai/models",
            endpoint="openai_models",
            view_func=models,
            methods=["POST"],
        )
        state.app.add_url_rule(
            "/api/openai/chat",
            endpoint="openai_chat",
            view_func=chat,
            methods=["POST"],
        )

    return blueprint

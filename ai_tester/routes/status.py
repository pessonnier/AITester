"""Aggregate system-status routes."""

from flask import Blueprint, jsonify

from ..destination_policy import HostConfirmationRequired
from ..gpu import GpuProbeError
from ..ollama import OllamaError
from ..services import AppServices


def create_status_blueprint(services: AppServices) -> Blueprint:
    blueprint = Blueprint("status", __name__)

    def status():
        result = {
            "gpu": {"available": False, "devices": []},
            "ollama": {"available": False, "models": []},
        }
        try:
            result["gpu"] = {
                "available": True,
                "devices": services.gpu_probe.status(),
            }
        except GpuProbeError as exc:
            result["gpu"]["error"] = str(exc)

        try:
            client = (
                services.make_ollama_client(services.default_ollama_url)
                if services.status_ollama_client is None
                else services.status_ollama_client
            )
            result["ollama"] = {
                "available": True,
                "models": client.list_models(),
            }
        except (HostConfirmationRequired, OllamaError, ValueError) as exc:
            result["ollama"]["error"] = str(exc)

        return jsonify(result)

    @blueprint.record_once
    def register_routes(state):
        state.app.add_url_rule(
            "/api/status",
            endpoint="status",
            view_func=status,
            methods=["GET"],
        )

    return blueprint

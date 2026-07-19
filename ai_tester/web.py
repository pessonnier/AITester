"""Flask application factory for AI Tester."""

from __future__ import annotations

from flask import Flask, jsonify

from .routes.common import FIELD_LIMITS, MAX_REQUEST_BYTES, ApiValidationError
from .routes.dashboard import create_dashboard_blueprint
from .routes.destinations import create_destinations_blueprint
from .routes.ollama import create_ollama_blueprint
from .routes.openai import create_openai_blueprint
from .routes.status import create_status_blueprint
from .services import AppServices


OPENAI_FIELD_LIMITS = FIELD_LIMITS


def create_app(
    *,
    gpu_probe=None,
    ollama_client=None,
    ollama_client_factory=None,
    openai_client_factory=None,
    destination_policy=None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

    @app.errorhandler(ApiValidationError)
    def validation_error(exc: ApiValidationError):
        return jsonify(error=str(exc)), 400

    services = AppServices.from_dependencies(
        gpu_probe=gpu_probe,
        ollama_client=ollama_client,
        ollama_client_factory=ollama_client_factory,
        openai_client_factory=openai_client_factory,
        destination_policy=destination_policy,
    )
    app.register_blueprint(create_dashboard_blueprint(services))
    app.register_blueprint(create_status_blueprint(services))
    app.register_blueprint(create_ollama_blueprint(services))
    app.register_blueprint(create_openai_blueprint(services))
    app.register_blueprint(create_destinations_blueprint(services))
    return app


app = create_app()

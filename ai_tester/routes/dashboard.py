"""Dashboard routes."""

from flask import Blueprint, render_template

from ..services import AppServices


def create_dashboard_blueprint(services: AppServices) -> Blueprint:
    blueprint = Blueprint("dashboard", __name__)

    def dashboard():
        return render_template(
            "index.html",
            default_ollama_url=services.default_ollama_url,
        )

    @blueprint.record_once
    def register_routes(state):
        state.app.add_url_rule(
            "/",
            endpoint="dashboard",
            view_func=dashboard,
            methods=["GET"],
        )

    return blueprint

"""Destination allowlist routes."""

from flask import Blueprint, jsonify

from ..services import AppServices
from .common import require_json_object


def create_destinations_blueprint(services: AppServices) -> Blueprint:
    blueprint = Blueprint("destinations", __name__)

    def add_allowed_host():
        payload = require_json_object()
        host = payload.get("host")
        if payload.get("confirmed") is not True:
            return jsonify(error="Une confirmation explicite est obligatoire"), 400
        if not isinstance(host, str) or not host.strip() or len(host) > 253:
            return jsonify(error="Le champ host est invalide"), 400
        try:
            allowed_host = services.destination_policy.add_host(host)
        except (OSError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(allowed_host=allowed_host)

    @blueprint.record_once
    def register_routes(state):
        for rule in (
            "/api/openai/allowed-hosts",
            "/api/destinations/allowed-hosts",
        ):
            state.app.add_url_rule(
                rule,
                endpoint="add_allowed_host",
                view_func=add_allowed_host,
                methods=["POST"],
            )

    return blueprint

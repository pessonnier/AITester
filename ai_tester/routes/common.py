"""Shared request validation for provider Blueprints."""

from flask import jsonify, request

from ..destination_policy import HostConfirmationRequired


MAX_REQUEST_BYTES = 64 * 1024
FIELD_LIMITS = {
    "base_url": 2_048,
    "api_key": 8_192,
    "model": 256,
    "prompt": 32_768,
    "system_prompt": 16_384,
}


class ApiValidationError(ValueError):
    """A client request failed validation before reaching a provider."""


def require_json_object() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ApiValidationError("Le corps JSON doit être un objet")
    return payload


def oversized_field(payload: dict, *field_names: str) -> str | None:
    for name in field_names:
        value = payload.get(name)
        if isinstance(value, str) and len(value) > FIELD_LIMITS[name]:
            return name
    return None


def confirmation_response(exc: HostConfirmationRequired):
    return jsonify(
        error=str(exc),
        confirmation_required=True,
        host=exc.host,
        addresses=list(exc.addresses),
    ), 403

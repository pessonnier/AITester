"""Small HTTP client for the Ollama API."""

from __future__ import annotations

import json
import socket
import string
from collections.abc import Callable
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.parse import urlsplit, urlunsplit

from .destination_policy import DestinationPolicyProtocol
from .http_transport import (
    InvalidJsonResponse,
    NoRedirectHandler,
    ResponseTooLarge,
    UnexpectedJsonStructure,
    open_without_redirects as _open_without_redirects,
    read_bounded_json_object,
)


_NoRedirectHandler = NoRedirectHandler
_HEX_DIGITS = frozenset(string.hexdigits)
MAX_OLLAMA_RESPONSE_BYTES = 10 * 1024 * 1024


class OllamaError(RuntimeError):
    """Base error raised by the Ollama integration."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama server cannot be reached."""


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns an invalid response."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://host.containers.internal:11434",
        *,
        timeout: float = 10.0,
        transport: Callable = _open_without_redirects,
        destination_policy: DestinationPolicyProtocol | None = None,
        resolver: Callable = socket.getaddrinfo,
    ) -> None:
        self.base_url = self._validate_base_url(
            base_url, destination_policy=destination_policy, resolver=resolver
        )
        self.timeout = timeout
        self._transport = transport

    @staticmethod
    def _validate_base_url(
        base_url: str,
        *,
        destination_policy: DestinationPolicyProtocol | None,
        resolver: Callable,
    ) -> str:
        if not isinstance(base_url, str):
            raise ValueError("URL Ollama invalide")
        parsed = urlsplit(base_url.strip())
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("URL Ollama invalide") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("URL Ollama invalide")
        path = parsed.path
        if any(
            character.isspace() or ord(character) < 32 or ord(character) >= 127
            for character in path
        ):
            raise ValueError("URL Ollama invalide")
        for index, character in enumerate(path):
            if character == "%" and (
                index + 2 >= len(path)
                or path[index + 1] not in _HEX_DIGITS
                or path[index + 2] not in _HEX_DIGITS
            ):
                raise ValueError("URL Ollama invalide")
        if destination_policy is not None:
            host = parsed.hostname.lower().rstrip(".")
            effective_port = port or (443 if parsed.scheme == "https" else 80)
            try:
                addresses = resolver(host, effective_port, type=socket.SOCK_STREAM)
            except (OSError, socket.gaierror) as exc:
                raise ValueError(
                    f"Résolution impossible pour l’hôte Ollama « {host} »"
                ) from exc
            if not addresses:
                raise ValueError(f"Résolution impossible pour l’hôte Ollama « {host} »")
            destination_policy.require_allowed(
                host, [address[4][0] for address in addresses]
            )
        normalized_path = path.rstrip("/")
        return urlunsplit(
            (parsed.scheme, parsed.netloc.lower(), normalized_path, "", "")
        )

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with self._transport(request, timeout=self.timeout) as response:
                body = read_bounded_json_object(
                    response, max_bytes=MAX_OLLAMA_RESPONSE_BYTES
                )
        except HTTPError as exc:
            raise OllamaResponseError(f"Ollama a répondu HTTP {exc.code}") from exc
        except ResponseTooLarge as exc:
            raise OllamaResponseError("Réponse Ollama trop volumineuse") from exc
        except UnexpectedJsonStructure as exc:
            raise OllamaResponseError("Réponse Ollama inattendue") from exc
        except InvalidJsonResponse as exc:
            raise OllamaResponseError("Réponse JSON Ollama invalide") from exc
        except (URLError, HTTPException, OSError) as exc:
            raise OllamaConnectionError(
                f"Ollama inaccessible à {self.base_url}: {exc}"
            ) from exc
        return body

    def list_models(self) -> list[dict]:
        body = self._request("/api/tags")
        models = body.get("models", [])
        if not isinstance(models, list):
            raise OllamaResponseError("Liste de modèles Ollama invalide")
        return [
            {
                "name": model.get("name", "inconnu"),
                "size": model.get("size"),
                "modified_at": model.get("modified_at"),
            }
            for model in models
            if isinstance(model, dict)
        ]

    def generate(self, model: str, prompt: str) -> str:
        body = self._request(
            "/api/generate",
            {"model": model, "prompt": prompt, "stream": False},
        )
        response = body.get("response")
        if not isinstance(response, str):
            raise OllamaResponseError("Réponse de génération Ollama invalide")
        return response

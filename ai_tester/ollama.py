"""Small HTTP client for the Ollama API."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    """Base error raised by the Ollama integration."""


class OllamaConnectionError(OllamaError):
    """Raised when the Ollama server cannot be reached."""


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns an invalid response."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout: float = 10.0,
        transport: Callable = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with self._transport(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except (URLError, TimeoutError, ConnectionError) as exc:
            raise OllamaConnectionError(f"Ollama inaccessible à {self.base_url}: {exc}") from exc
        except HTTPError as exc:
            raise OllamaResponseError(f"Ollama a répondu HTTP {exc.code}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise OllamaResponseError("Réponse JSON Ollama invalide") from exc
        if not isinstance(body, dict):
            raise OllamaResponseError("Réponse Ollama inattendue")
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

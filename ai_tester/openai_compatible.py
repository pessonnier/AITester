"""Client for OpenAI and OpenAI-compatible HTTP APIs."""

from __future__ import annotations

import json
import os
import socket
import string
import unicodedata
from collections.abc import Callable, Iterable
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .destination_policy import DestinationPolicy


MAX_OPENAI_RESPONSE_BYTES = 10 * 1024 * 1024
_HEX_DIGITS = frozenset(string.hexdigits)


class OpenAIError(RuntimeError):
    """Base error for OpenAI-compatible providers."""


class OpenAIConnectionError(OpenAIError):
    """Raised when the configured API cannot be reached."""


class OpenAIResponseError(OpenAIError):
    """Raised when the configured API returns an invalid response."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(request: Request, *, timeout: float):
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def _environment_allowed_hosts() -> set[str]:
    configured = os.getenv("OPENAI_ALLOWED_HOSTS", "")
    return {
        host.strip().lower().rstrip(".")
        for host in configured.replace(",", " ").split()
        if host.strip() and host.strip() != "*"
    }


class OpenAIClient:
    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        *,
        api_key: str = "",
        timeout: float = 30.0,
        transport: Callable | None = None,
        allowed_hosts: Iterable[str] | None = None,
        resolver: Callable = socket.getaddrinfo,
        destination_policy: DestinationPolicy | None = None,
    ) -> None:
        self._validate_api_key(api_key)
        self.destination_policy = destination_policy or DestinationPolicy()
        self._base = self._validate_base_url(
            base_url,
            api_key=api_key,
            allowed_hosts=allowed_hosts,
            resolver=resolver,
            destination_policy=self.destination_policy,
        )
        self.base_url = urlunsplit(self._base)
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport or _open_without_redirects

    @staticmethod
    def _validate_api_key(api_key: str) -> None:
        if not isinstance(api_key, str) or any(
            unicodedata.category(character) == "Cc" for character in api_key
        ):
            raise ValueError("Clé API OpenAI invalide : caractères de contrôle interdits")
        try:
            api_key.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ValueError("Clé API OpenAI invalide : caractères non pris en charge") from exc

    @staticmethod
    def _validate_base_url(
        base_url: str,
        *,
        api_key: str,
        allowed_hosts: Iterable[str] | None,
        resolver: Callable,
        destination_policy: DestinationPolicy,
    ) -> SplitResult:
        if not isinstance(base_url, str):
            raise ValueError("URL OpenAI invalide : utilisez une URL HTTP ou HTTPS")
        if any(
            character.isspace() or unicodedata.category(character) == "Cc"
            for character in base_url
        ):
            raise ValueError(
                "URL OpenAI invalide : espaces et caractères de contrôle interdits"
            )
        parsed = urlsplit(base_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("URL OpenAI invalide : port incorrect") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "URL OpenAI invalide : schéma HTTP(S), hôte et chemin uniquement"
            )
        if api_key and parsed.scheme != "https":
            raise ValueError("Une clé API OpenAI exige une connexion HTTPS")

        try:
            parsed.path.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("URL OpenAI invalide : le chemin doit être encodé") from exc
        for index, character in enumerate(parsed.path):
            if character == "%" and (
                index + 2 >= len(parsed.path)
                or parsed.path[index + 1] not in _HEX_DIGITS
                or parsed.path[index + 2] not in _HEX_DIGITS
            ):
                raise ValueError("URL OpenAI invalide : encodage du chemin incorrect")

        host = parsed.hostname.lower().rstrip(".")
        explicit_hosts = _environment_allowed_hosts()
        if allowed_hosts is not None:
            explicit_hosts |= {
                value.strip().lower().rstrip(".")
                for value in allowed_hosts
                if value.strip() and value.strip() != "*"
            }
        effective_port = port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = resolver(host, effective_port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(f"Résolution impossible pour l’hôte OpenAI « {host} »") from exc
        if not addresses:
            raise ValueError(f"Résolution impossible pour l’hôte OpenAI « {host} »")
        if host not in explicit_hosts:
            destination_policy.require_allowed(
                host, [address[4][0] for address in addresses]
            )

        path = parsed.path.rstrip("/")
        netloc = parsed.netloc.lower()
        return SplitResult(parsed.scheme, netloc, path, "", "")

    def _endpoint(self, path: str) -> str:
        endpoint_path = f"{self._base.path}/{path.lstrip('/')}"
        return urlunsplit(self._base._replace(path=endpoint_path))

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self._endpoint(path), data=data, headers=headers)
        try:
            with self._transport(request, timeout=self.timeout) as response:
                content_length = getattr(response, "headers", {}).get("Content-Length")
                try:
                    declared_length = int(content_length) if content_length is not None else None
                except (TypeError, ValueError):
                    declared_length = None
                if (
                    declared_length is not None
                    and declared_length > MAX_OPENAI_RESPONSE_BYTES
                ):
                    raise OpenAIResponseError("Réponse OpenAI trop volumineuse")
                raw_body = response.read(MAX_OPENAI_RESPONSE_BYTES + 1)
                if len(raw_body) > MAX_OPENAI_RESPONSE_BYTES:
                    raise OpenAIResponseError("Réponse OpenAI trop volumineuse")
                body = json.loads(raw_body)
        except HTTPError as exc:
            raise OpenAIResponseError(f"L’API OpenAI a répondu HTTP {exc.code}") from exc
        except OpenAIResponseError:
            raise
        except (URLError, HTTPException, OSError) as exc:
            raise OpenAIConnectionError(
                f"API OpenAI inaccessible à {self.base_url}: {exc}"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise OpenAIResponseError("Réponse JSON OpenAI invalide") from exc
        if not isinstance(body, dict):
            raise OpenAIResponseError("Structure de réponse OpenAI invalide")
        return body

    def list_models(self) -> list[str]:
        body = self._request("models")
        models = body.get("data")
        if not isinstance(models, list):
            raise OpenAIResponseError("Liste de modèles OpenAI invalide")
        return [
            model["id"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        ]

    def chat(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        top_p: float = 1.0,
        max_tokens: int | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        body = self._request("chat/completions", payload)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIResponseError("Réponse de complétion OpenAI invalide") from exc
        if not isinstance(content, str):
            raise OpenAIResponseError("Réponse de complétion OpenAI invalide")
        return content

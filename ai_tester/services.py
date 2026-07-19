"""Typed dependency container used by the Flask application Blueprints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .destination_policy import DestinationPolicy, DestinationPolicyProtocol
from .gpu import SystemGpuProbe
from .ollama import OllamaClient
from .openai_compatible import OpenAIClient


class GpuProbeProtocol(Protocol):
    def status(self) -> list[dict]: ...


class OllamaClientProtocol(Protocol):
    def list_models(self) -> list[dict]: ...

    def generate(self, model: str, prompt: str) -> str: ...


class OpenAIClientProtocol(Protocol):
    def list_models(self) -> list[str]: ...

    def chat(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        top_p: float = 1.0,
        max_tokens: int | None = None,
    ) -> str: ...


class OllamaClientFactory(Protocol):
    def __call__(self, base_url: str) -> OllamaClientProtocol: ...


class OpenAIClientFactory(Protocol):
    def __call__(
        self,
        base_url: str,
        *,
        api_key: str = "",
    ) -> OpenAIClientProtocol: ...


@dataclass(frozen=True, slots=True)
class AppServices:
    gpu_probe: GpuProbeProtocol
    status_ollama_client: OllamaClientProtocol | None
    make_ollama_client: OllamaClientFactory
    make_openai_client: OpenAIClientFactory
    destination_policy: DestinationPolicyProtocol
    default_ollama_url: str

    @classmethod
    def from_dependencies(
        cls,
        *,
        gpu_probe: GpuProbeProtocol | None = None,
        ollama_client: OllamaClientProtocol | None = None,
        ollama_client_factory: OllamaClientFactory | None = None,
        openai_client_factory: OpenAIClientFactory | None = None,
        destination_policy: DestinationPolicyProtocol | None = None,
    ) -> AppServices:
        policy = (
            DestinationPolicy() if destination_policy is None else destination_policy
        )

        if ollama_client_factory is not None:
            make_ollama_client = ollama_client_factory
        elif ollama_client is not None:

            def fixed_ollama_client(base_url: str) -> OllamaClientProtocol:
                return ollama_client

            make_ollama_client = fixed_ollama_client
        else:

            def default_ollama_client(base_url: str) -> OllamaClientProtocol:
                return OllamaClient(base_url, destination_policy=policy)

            make_ollama_client = default_ollama_client

        if openai_client_factory is not None:
            make_openai_client = openai_client_factory
        else:

            def default_openai_client(
                base_url: str,
                *,
                api_key: str = "",
            ) -> OpenAIClientProtocol:
                return OpenAIClient(
                    base_url,
                    api_key=api_key,
                    destination_policy=policy,
                )

            make_openai_client = default_openai_client

        return cls(
            gpu_probe=SystemGpuProbe() if gpu_probe is None else gpu_probe,
            status_ollama_client=ollama_client,
            make_ollama_client=make_ollama_client,
            make_openai_client=make_openai_client,
            destination_policy=policy,
            default_ollama_url=os.getenv(
                "OLLAMA_BASE_URL", "http://host.containers.internal:11434"
            ),
        )

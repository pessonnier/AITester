"""Persistent allowlist for OpenAI-compatible API destinations."""

from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol


DEFAULT_ALLOWED_NETWORKS = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
)
DEFAULT_ALLOWED_HOSTS = (
    "api.openai.com",
    "host.containers.internal",
    "host.docker.internal",
    "localhost",
    "ollama",
)
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "allowed_destinations.json"
)
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_WRITE_LOCK = threading.RLock()


class DestinationPolicyProtocol(Protocol):
    def require_allowed(
        self,
        host: str,
        addresses: list[str] | tuple[str, ...],
    ) -> None: ...

    def add_host(self, host: str) -> str: ...


class HostConfirmationRequired(ValueError):
    """Raised when a destination needs explicit administrator approval."""

    def __init__(self, host: str, addresses: list[str] | tuple[str, ...]):
        self.host = host
        self.addresses = tuple(dict.fromkeys(addresses))
        super().__init__(f"Le domaine « {host} » doit être confirmé")


def _normalize_host(host: str) -> str:
    if not isinstance(host, str):
        raise ValueError("Nom d’hôte invalide")
    candidate = host.strip().lower().rstrip(".")
    if not candidate or candidate == "*" or "*" in candidate:
        raise ValueError("Nom d’hôte invalide : les jokers sont interdits")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass
    try:
        ascii_host = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Nom d’hôte invalide") from exc
    if len(ascii_host) > 253 or any(
        not _HOST_LABEL.fullmatch(label) for label in ascii_host.split(".")
    ):
        raise ValueError("Nom d’hôte invalide")
    return ascii_host


class DestinationPolicy:
    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = (
            path or os.getenv("AI_TESTER_ALLOWED_DESTINATIONS") or DEFAULT_CONFIG_PATH
        )
        self.path = Path(configured_path)
        with self._exclusive_lock():
            if not self.path.exists():
                self._write_unlocked(
                    {
                        "allowed_hosts": list(DEFAULT_ALLOWED_HOSTS),
                        "allowed_networks": list(DEFAULT_ALLOWED_NETWORKS),
                    }
                )
            self._load()

    @contextmanager
    def _exclusive_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        with _WRITE_LOCK, lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self) -> None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            hosts = document["allowed_hosts"]
            networks = document["allowed_networks"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                f"Configuration des destinations invalide : {self.path}"
            ) from exc
        if not isinstance(hosts, list) or not isinstance(networks, list):
            raise ValueError(f"Configuration des destinations invalide : {self.path}")
        self.allowed_hosts = tuple(sorted({_normalize_host(host) for host in hosts}))
        try:
            parsed_networks = tuple(
                ipaddress.ip_network(network, strict=True) for network in networks
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Configuration des destinations invalide : {self.path}"
            ) from exc
        self._networks = parsed_networks
        self.allowed_networks = tuple(str(network) for network in parsed_networks)

    def _write_unlocked(self, document: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as temporary:
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def require_allowed(
        self, host: str, addresses: list[str] | tuple[str, ...]
    ) -> None:
        with self._exclusive_lock():
            self._load()
        normalized = _normalize_host(host)
        if normalized in self.allowed_hosts:
            return
        try:
            parsed_addresses = tuple(
                ipaddress.ip_address(address) for address in addresses
            )
        except ValueError as exc:
            raise ValueError("Adresse de destination invalide") from exc
        try:
            host_address = ipaddress.ip_address(normalized)
        except ValueError:
            host_address = None
        if host_address is not None and parsed_addresses:
            if all(
                any(address in network for network in self._networks)
                for address in parsed_addresses
            ):
                return
        raise HostConfirmationRequired(
            normalized, [str(address) for address in parsed_addresses]
        )

    def add_host(self, host: str) -> str:
        normalized = _normalize_host(host)
        with self._exclusive_lock():
            self._load()
            hosts = sorted(set(self.allowed_hosts) | {normalized})
            self._write_unlocked(
                {
                    "allowed_hosts": hosts,
                    "allowed_networks": list(self.allowed_networks),
                }
            )
            self._load()
        return normalized

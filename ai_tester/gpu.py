"""AMD GPU diagnostics through rocm-smi."""

from __future__ import annotations

import json
import subprocess
import csv
from io import StringIO
from collections.abc import Callable


class GpuProbeError(RuntimeError):
    """Raised when GPU diagnostics cannot be collected."""


def _number(value, cast=float):
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _find_value(card: dict, prefixes: tuple[str, ...]):
    for key, value in card.items():
        if any(key.startswith(prefix) for prefix in prefixes):
            return value
    return None


class GpuProbe:
    def __init__(self, *, runner: Callable = subprocess.run, timeout: float = 10.0):
        self._runner = runner
        self.timeout = timeout

    def status(self) -> list[dict]:
        command = [
            "rocm-smi",
            "--showproductname",
            "--showuse",
            "--showtemp",
            "--showmeminfo",
            "vram",
            "--json",
        ]
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise GpuProbeError("rocm-smi est introuvable") from exc
        except subprocess.TimeoutExpired as exc:
            raise GpuProbeError("rocm-smi a dépassé le délai autorisé") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "erreur inconnue").strip()
            raise GpuProbeError(f"rocm-smi a échoué: {detail}") from exc

        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise GpuProbeError("Sortie JSON rocm-smi invalide") from exc
        if not isinstance(payload, dict):
            raise GpuProbeError("Structure rocm-smi inattendue")

        devices = []
        for card_id, card in payload.items():
            if not isinstance(card, dict):
                continue
            devices.append({
                "id": card_id,
                "vendor": "AMD",
                "name": _find_value(card, ("Card series", "Card model", "Card SKU")) or "GPU AMD inconnu",
                "utilization_percent": _number(_find_value(card, ("GPU use",))),
                "temperature_c": _number(_find_value(card, ("Temperature",))),
                "vram_total_bytes": _number(_find_value(card, ("VRAM Total Memory",)), int),
                "vram_used_bytes": _number(_find_value(card, ("VRAM Total Used Memory",)), int),
            })
        return devices


class NvidiaGpuProbe:
    """Collect NVIDIA GPU metrics using nvidia-smi's stable CSV interface."""

    def __init__(self, *, runner: Callable = subprocess.run, timeout: float = 10.0):
        self._runner = runner
        self.timeout = timeout

    def status(self) -> list[dict]:
        command = [
            "nvidia-smi",
            "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.total,memory.used",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise GpuProbeError("nvidia-smi est introuvable") from exc
        except subprocess.TimeoutExpired as exc:
            raise GpuProbeError("nvidia-smi a dépassé le délai autorisé") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "erreur inconnue").strip()
            raise GpuProbeError(f"nvidia-smi a échoué: {detail}") from exc

        devices = []
        for row in csv.reader(StringIO(result.stdout), skipinitialspace=True):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) != 6:
                raise GpuProbeError("Sortie CSV nvidia-smi invalide")
            gpu_id, name, utilization, temperature, total_mib, used_mib = (
                value.strip() for value in row
            )
            devices.append({
                "id": gpu_id,
                "vendor": "NVIDIA",
                "name": name,
                "utilization_percent": _number(utilization),
                "temperature_c": _number(temperature),
                "vram_total_bytes": (_number(total_mib, int) or 0) * 1024 * 1024,
                "vram_used_bytes": (_number(used_mib, int) or 0) * 1024 * 1024,
            })
        return devices


class SystemGpuProbe:
    """Aggregate every available GPU backend without coupling vendors."""

    def __init__(self, probes=None):
        self.probes = probes or [GpuProbe(), NvidiaGpuProbe()]

    def status(self) -> list[dict]:
        devices = []
        errors = []
        successful_backend = False
        for probe in self.probes:
            try:
                devices.extend(probe.status())
                successful_backend = True
            except GpuProbeError as exc:
                errors.append(str(exc))
        if not successful_backend:
            raise GpuProbeError(" ; ".join(errors) or "Aucun backend GPU configuré")
        return devices

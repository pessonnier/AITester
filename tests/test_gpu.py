import json
import subprocess

import pytest

from ai_tester.gpu import GpuProbe, GpuProbeError, NvidiaGpuProbe, SystemGpuProbe


def completed(payload: dict):
    return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")


def test_probe_normalizes_rocm_smi_card_output():
    payload = {
        "card0": {
            "Card series": "AMD Radeon RX 7900 XTX",
            "GPU use (%)": "17",
            "Temperature (Sensor edge) (C)": "54.0",
            "VRAM Total Memory (B)": "25753026560",
            "VRAM Total Used Memory (B)": "8589934592",
        }
    }
    probe = GpuProbe(runner=lambda *args, **kwargs: completed(payload))

    assert probe.status() == [
        {
            "id": "card0",
            "vendor": "AMD",
            "name": "AMD Radeon RX 7900 XTX",
            "utilization_percent": 17.0,
            "temperature_c": 54.0,
            "vram_total_bytes": 25_753_026_560,
            "vram_used_bytes": 8_589_934_592,
        }
    ]


def test_probe_uses_rocm_smi_json_command():
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return completed({})

    GpuProbe(runner=runner).status()

    assert captured["command"] == [
        "rocm-smi",
        "--showproductname",
        "--showuse",
        "--showtemp",
        "--showmeminfo",
        "vram",
        "--json",
    ]
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "check": True,
        "timeout": 10.0,
    }


def test_probe_reports_missing_rocm_smi():
    def runner(*args, **kwargs):
        raise FileNotFoundError

    with pytest.raises(GpuProbeError, match="rocm-smi est introuvable"):
        GpuProbe(runner=runner).status()


def test_nvidia_probe_normalizes_csv_output():
    output = (
        "0, NVIDIA RTX 4090, 28, 49, 24564, 4096\n1, NVIDIA L40S, 3, 41, 46068, 1024\n"
    )

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    devices = NvidiaGpuProbe(runner=runner).status()

    assert devices == [
        {
            "id": "0",
            "vendor": "NVIDIA",
            "name": "NVIDIA RTX 4090",
            "utilization_percent": 28.0,
            "temperature_c": 49.0,
            "vram_total_bytes": 24_564 * 1024 * 1024,
            "vram_used_bytes": 4_096 * 1024 * 1024,
        },
        {
            "id": "1",
            "vendor": "NVIDIA",
            "name": "NVIDIA L40S",
            "utilization_percent": 3.0,
            "temperature_c": 41.0,
            "vram_total_bytes": 46_068 * 1024 * 1024,
            "vram_used_bytes": 1_024 * 1024 * 1024,
        },
    ]


def test_nvidia_probe_uses_machine_readable_query():
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    NvidiaGpuProbe(runner=runner).status()

    assert captured["command"] == [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]


def test_system_probe_keeps_nvidia_when_rocm_is_unavailable():
    class MissingAmd:
        def status(self):
            raise GpuProbeError("rocm-smi est introuvable")

    class AvailableNvidia:
        def status(self):
            return [{"id": "0", "vendor": "NVIDIA", "name": "RTX"}]

    assert SystemGpuProbe([MissingAmd(), AvailableNvidia()]).status() == [
        {"id": "0", "vendor": "NVIDIA", "name": "RTX"}
    ]


def test_system_probe_reports_all_unavailable_backends():
    class Missing:
        def __init__(self, message):
            self.message = message

        def status(self):
            raise GpuProbeError(self.message)

    with pytest.raises(GpuProbeError, match="rocm-smi.*nvidia-smi"):
        SystemGpuProbe(
            [Missing("rocm-smi absent"), Missing("nvidia-smi absent")]
        ).status()


def test_system_probe_accepts_an_explicitly_empty_backend_list():
    with pytest.raises(GpuProbeError, match="Aucun backend GPU configuré"):
        SystemGpuProbe([]).status()

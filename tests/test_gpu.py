import json
import subprocess

import pytest

from ai_tester.gpu import GpuProbe, GpuProbeError


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

    assert probe.status() == [{
        "id": "card0",
        "name": "AMD Radeon RX 7900 XTX",
        "utilization_percent": 17.0,
        "temperature_c": 54.0,
        "vram_total_bytes": 25_753_026_560,
        "vram_used_bytes": 8_589_934_592,
    }]


def test_probe_uses_rocm_smi_json_command():
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return completed({})

    GpuProbe(runner=runner).status()

    assert captured["command"] == ["rocm-smi", "--showproductname", "--showuse", "--showtemp", "--showmeminfo", "vram", "--json"]
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

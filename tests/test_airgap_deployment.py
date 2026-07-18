from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGE_ID = f"sha256:{'0' * 64}"
TEST_MANIFEST = (
    "IMAGE_REF=ai-tester:0.1.0\n"
    f"IMAGE_ID={TEST_IMAGE_ID}\n"
    "IMAGE_ARCHIVE=ai-tester-image.tar\n"
    "ARCH=x86_64\n"
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def write_test_bundle(directory: Path, manifest_text: str = TEST_MANIFEST) -> Path:
    installer = directory / "install.sh"
    shutil.copy2(ROOT / "deploy/airgap/install.sh", installer)
    installer.chmod(0o755)
    image = directory / "ai-tester-image.tar"
    image.write_bytes(b"offline-image")
    manifest = directory / "MANIFEST"
    manifest.write_text(manifest_text)
    checksums = []
    for path in (image, manifest, installer):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums.append(f"{digest}  {path.name}\n")
    (directory / "SHA256SUMS").write_text("".join(checksums))
    return installer


def test_container_image_is_non_root_and_uses_production_server():
    containerfile = read("Containerfile")

    assert "USER ai-tester" in containerfile
    assert "waitress-serve" in containerfile
    assert "AI_TESTER_ALLOWED_DESTINATIONS=/data/allowed_destinations.json" in containerfile
    assert "OLLAMA_BASE_URL=http://host.containers.internal:11434" in containerfile
    assert "HEALTHCHECK" in containerfile
    assert "@sha256:" in containerfile
    assert "--require-hashes" in containerfile
    assert "requirements.lock" in containerfile
    assert "rocm/dev-ubuntu-24.04:7.2.4@sha256:" in containerfile
    assert "test -x /opt/rocm/bin/rocm-smi" in containerfile
    assert "deploy/gpu/rocm-smi" in containerfile
    assert "deploy/gpu/nvidia-smi" in containerfile


def test_gpu_command_wrappers_are_valid_and_actionable():
    for command in ("rocm-smi", "nvidia-smi"):
        path = ROOT / "deploy/gpu" / command
        syntax = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True
        )
        assert syntax.returncode == 0, syntax.stderr
        assert "exec" in path.read_text()


def test_docker_and_podman_contexts_exclude_local_secrets():
    dockerignore = read(".dockerignore")
    containerignore = read(".containerignore")

    assert dockerignore == containerignore
    patterns = dockerignore.splitlines()
    for excluded in (
        ".git",
        "**/.git",
        ".venv",
        ".tmp",
        ".env*",
        "**/.env*",
        ".ssh",
        "*.pem",
        "*.key",
    ):
        assert excluded in patterns


def test_airgap_scripts_have_valid_bash_syntax():
    for relative_path in (
        "deploy/airgap/build-bundle.sh",
        "deploy/airgap/install.sh",
    ):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / relative_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_connected_builder_exports_image_and_checksums():
    script = read("deploy/airgap/build-bundle.sh")

    assert "docker save" in script
    assert "podman save" in script
    assert "SHA256SUMS" in script
    assert '"${BUNDLE_NAME}.sha256"' in script
    assert "install.sh" in script
    assert "tar" in script


def test_offline_installer_never_pulls_and_verifies_before_loading():
    script = read("deploy/airgap/install.sh")

    assert "set -Eeuo pipefail" in script
    checksum_position = script.index("sha256sum -c SHA256SUMS")
    load_position = script.index('load -i "$IMAGE_ARCHIVE"')
    assert checksum_position < load_position
    assert " pull " not in script
    assert "--pull=never" in script
    assert "host.containers.internal:11434" in script
    assert "host.docker.internal:11434" in script
    assert "--add-host=host.docker.internal:host-gateway" in script
    assert "AI_TESTER_ALLOWED_DESTINATIONS=/data/allowed_destinations.json" in script
    assert '--publish "${BIND_ADDRESS}:${PORT}:5000"' in script
    assert "--cap-drop=ALL" in script
    assert "--security-opt=no-new-privileges" in script
    assert "--read-only" in script
    assert "--gpu auto|amd|nvidia|all|none" in script
    assert "--device=/dev/kfd" in script
    assert "--device=/dev/dri" in script
    assert "--group-add=keep-groups" in script
    assert "--gpus=all" in script
    assert "--device=nvidia.com/gpu=all" in script
    assert "--privileged" not in script
    assert "seccomp=unconfined" not in script
    assert "[[ -c /dev/kfd" in script
    assert "gpu_gid == 0" in script
    assert "AI_TESTER_GPU_DEVICE_ROOT" not in script
    container_inspect = script.index('container inspect "${NAME}"')
    assert script.index("GPU AMD demandé") < container_inspect
    assert script.index("Runtime NVIDIA non configuré") < container_inspect
    preflight_create = script.index('"${RUNTIME}" create --name')
    existing_remove = script.index('"${RUNTIME}" rm --force "${NAME}"')
    assert preflight_create < existing_remove


def test_readme_documents_air_gapped_deployment():
    readme = read("README.md")

    assert "## Déploiement air-gapped" in readme
    assert "build-bundle.sh" in readme
    assert "SHA256SUMS" in readme
    assert "install.sh" in readme
    assert "aucun accès Internet" in readme
    assert "### Accès GPU AMD" in readme
    assert "### Accès GPU NVIDIA" in readme
    assert "--gpu amd" in readme
    assert "--gpu nvidia" in readme


def test_offline_installer_rejects_unknown_gpu_mode_before_runtime(tmp_path):
    installer = tmp_path / "install.sh"
    shutil.copy2(ROOT / "deploy/airgap/install.sh", installer)
    installer.chmod(0o755)

    result = subprocess.run(
        [str(installer), "--gpu", "cuda", "--replace"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Mode GPU invalide" in result.stderr
    assert "SHA256SUMS" not in result.stderr


@pytest.mark.parametrize(
    (
        "runtime",
        "expected_url",
        "expected_runtime_options",
        "configured_url",
        "gpu_mode",
    ),
    [
        ("podman", "http://host.containers.internal:11434", [], None, "none"),
        (
            "docker",
            "http://host.docker.internal:11434",
            ["--add-host=host.docker.internal:host-gateway"],
            None,
            "none",
        ),
        (
            "podman",
            "https://ollama.example.com/models/@latest/%41",
            [],
            "https://ollama.example.com/models/@latest/%41",
            "none",
        ),

        (
            "podman",
            "http://host.containers.internal:11434",
            ["--device=nvidia.com/gpu=all", "NVIDIA_DRIVER_CAPABILITIES=utility"],
            None,
            "nvidia",
        ),
        (
            "docker",
            "http://host.docker.internal:11434",
            ["--gpus=all", "NVIDIA_DRIVER_CAPABILITIES=utility"],
            None,
            "nvidia",
        ),

    ],
)
def test_offline_installer_loads_and_starts_without_network(
    tmp_path,
    runtime,
    expected_url,
    expected_runtime_options,
    configured_url,
    gpu_mode,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    installer = bundle / "install.sh"
    shutil.copy2(ROOT / "deploy/airgap/install.sh", installer)
    installer.chmod(0o755)
    image = bundle / "ai-tester-image.tar"
    image.write_bytes(b"offline-image")
    manifest = bundle / "MANIFEST"
    manifest.write_text(TEST_MANIFEST)

    checksum_lines = []
    for path in (image, manifest, installer):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {path.name}\n")
    (bundle / "SHA256SUMS").write_text("".join(checksum_lines))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_runtime = fake_bin / runtime
    fake_runtime.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_RUNTIME_LOG\"\n"
        "[[ $1 == info ]] && printf '{\"nvidia\":{}}\\n' && exit 0\n"
        f"[[ $1 == image && $2 == inspect ]] && printf '{TEST_IMAGE_ID}\\n' && exit 0\n"
        "[[ $1 == container && $2 == inspect ]] && exit 1\n"
        "[[ $1 == run ]] && printf 'container-id\\n'\n"
        "exit 0\n"
    )
    fake_runtime.chmod(0o755)
    if gpu_mode in {"nvidia", "all"}:
        fake_nvidia_smi = fake_bin / "nvidia-smi"
        fake_nvidia_smi.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake_nvidia_smi.chmod(0o755)
        fake_nvidia_ctk = fake_bin / "nvidia-ctk"
        fake_nvidia_ctk.write_text(
            "#!/usr/bin/env bash\nprintf 'nvidia.com/gpu=all\\n'\n"
        )
        fake_nvidia_ctk.chmod(0o755)
    log = tmp_path / "runtime.log"
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CONTAINER_RUNTIME": runtime,
        "FAKE_RUNTIME_LOG": str(log),
    }

    command = [str(installer), "--port", "8080", "--gpu", gpu_mode]
    if configured_url:
        command.extend(("--ollama-url", configured_url))
    result = subprocess.run(
        command,
        cwd=bundle,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    calls = log.read_text()
    assert "load -i ai-tester-image.tar" in calls
    assert "--publish 127.0.0.1:8080:5000" in calls
    assert f"OLLAMA_BASE_URL={expected_url}" in calls
    assert "exec ai-tester python3 -c" in calls
    for expected_runtime_option in expected_runtime_options:
        assert expected_runtime_option in calls
    if gpu_mode == "none":
        assert "--device=/dev/kfd" not in calls
        assert "--device=nvidia.com/gpu=all" not in calls
        assert "--gpus=all" not in calls


def test_connected_builder_creates_transferable_bundle(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_runtime = fake_bin / "docker"
    fake_runtime.write_text(
        "#!/usr/bin/env bash\n"
        f"if [[ $1 == image && $2 == inspect ]]; then printf 'amd64 {TEST_IMAGE_ID}\\n'; exit 0; fi\n"
        "if [[ $1 == save ]]; then\n"
        "  while (($#)); do\n"
        "    if [[ $1 == --output ]]; then printf 'fake-image' > \"$2\"; exit 0; fi\n"
        "    shift\n"
        "  done\n"
        "fi\n"
        "exit 0\n"
    )
    fake_runtime.chmod(0o755)
    output_dir = tmp_path / "dist"
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CONTAINER_RUNTIME": "docker",
        "OUTPUT_DIR": str(output_dir),
        "VERSION": "test",
        "ARCH": "x86_64",
        "ALLOW_DIRTY": "1",
    }

    result = subprocess.run(
        [str(ROOT / "deploy/airgap/build-bundle.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    bundle = output_dir / "ai-tester-airgap-test-x86_64.tar.gz"
    checksum = output_dir / f"{bundle.name}.sha256"
    assert bundle.is_file()
    assert checksum.is_file()
    verified = subprocess.run(
        ["sha256sum", "-c", checksum.name],
        cwd=output_dir,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stderr
    with tarfile.open(bundle) as archive:
        names = set(archive.getnames())
        manifest_member = archive.extractfile("ai-tester-airgap/MANIFEST")
        assert manifest_member is not None
        manifest_text = manifest_member.read().decode()
    assert "ai-tester-airgap/ai-tester-image-test-x86_64.tar" in names
    assert "ai-tester-airgap/SHA256SUMS" in names
    assert "ai-tester-airgap/install.sh" in names
    assert "ai-tester-airgap/requirements.lock" in names
    assert "GPU_BASE_IMAGE=rocm/dev-ubuntu-24.04:7.2.4@sha256:" in manifest_text
    assert f"IMAGE_ID={TEST_IMAGE_ID}" in manifest_text
    assert "ARCH=x86_64" in manifest_text
    assert "LOCK_SHA256=" in manifest_text
    assert "SOURCE_COMMIT=" in manifest_text


def test_connected_builder_rejects_path_traversal_in_version(tmp_path):
    environment = os.environ | {
        "CONTAINER_RUNTIME": "docker",
        "VERSION": "../../escape",
        "OUTPUT_DIR": str(tmp_path / "dist"),
    }

    result = subprocess.run(
        [str(ROOT / "deploy/airgap/build-bundle.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "VERSION ou ARCH invalide" in result.stderr


def test_connected_builder_rejects_unpinned_base_image(tmp_path):
    environment = os.environ | {
        "CONTAINER_RUNTIME": "docker",
        "GPU_BASE_IMAGE": "rocm/dev-ubuntu-24.04:7.2.4",
        "OUTPUT_DIR": str(tmp_path / "dist"),
    }

    result = subprocess.run(
        [str(ROOT / "deploy/airgap/build-bundle.sh")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "GPU_BASE_IMAGE doit être épinglée par digest sha256" in result.stderr


def test_connected_builder_rejects_architecture_label_mismatch(tmp_path):
    result = subprocess.run(
        [str(ROOT / "deploy/airgap/build-bundle.sh")],
        cwd=tmp_path,
        env=os.environ | {"ARCH": "aarch64", "CONTAINER_RUNTIME": "docker"},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "ne correspond pas à l’architecture hôte" in result.stderr


def test_offline_installer_rejects_bundle_for_another_architecture(tmp_path):
    wrong_arch_manifest = TEST_MANIFEST.replace("ARCH=x86_64", "ARCH=aarch64")
    installer = write_test_bundle(tmp_path, wrong_arch_manifest)

    result = subprocess.run(
        [str(installer), "--no-start"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "Architecture incompatible" in result.stderr


def test_preflight_failure_preserves_existing_container(tmp_path):
    installer = write_test_bundle(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    runtime_log = tmp_path / "runtime.log"
    fake_runtime = fake_bin / "podman"
    fake_runtime.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_RUNTIME_LOG\"\n"
        "[[ $1 == container && $2 == inspect ]] && exit 0\n"
        f"[[ $1 == image && $2 == inspect ]] && printf '{TEST_IMAGE_ID}\\n' && exit 0\n"
        "[[ $1 == create ]] && exit 42\n"
        "exit 0\n"
    )
    fake_runtime.chmod(0o755)

    result = subprocess.run(
        [str(installer), "--runtime", "podman", "--gpu", "none", "--replace"],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_RUNTIME_LOG": str(runtime_log),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    calls = runtime_log.read_text().splitlines()
    assert any(call.startswith("create ") for call in calls)
    assert "rm --force ai-tester" not in calls
    assert "Le moteur a refusé" in result.stderr


def test_offline_installer_rejects_tampered_image_before_runtime(tmp_path):
    installer = tmp_path / "install.sh"
    shutil.copy2(ROOT / "deploy/airgap/install.sh", installer)
    installer.chmod(0o755)
    image = tmp_path / "ai-tester-image.tar"
    image.write_bytes(b"expected-image")
    manifest = tmp_path / "MANIFEST"
    manifest.write_text(TEST_MANIFEST)
    checksum_lines = []
    for path in (image, manifest, installer):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {path.name}\n")
    (tmp_path / "SHA256SUMS").write_text("".join(checksum_lines))
    image.write_bytes(b"tampered-image")

    result = subprocess.run(
        [str(installer), "--no-start"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "FAILED" in result.stdout


@pytest.mark.parametrize(
    "invalid_url",
    [
        "ftp://invalid",
        "http://",
        "https://",
        "http://user@host",
        "http://host?query=1",
        "http://host#fragment",
        "http://host:0",
        "http://host:65536",
        "http://host name",
        "http://host/%zz",
        "http://bad_host",
        "http://1..2",
        "http://999.999.999.999",
        "http://-bad.example",
        "http://bad-.example",
    ],
)
def test_invalid_ollama_url_cannot_remove_existing_container(tmp_path, invalid_url):
    installer = tmp_path / "install.sh"
    shutil.copy2(ROOT / "deploy/airgap/install.sh", installer)
    installer.chmod(0o755)
    image = tmp_path / "ai-tester-image.tar"
    image.write_bytes(b"offline-image")
    manifest = tmp_path / "MANIFEST"
    manifest.write_text(TEST_MANIFEST)
    checksum_lines = []
    for path in (image, manifest, installer):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {path.name}\n")
    (tmp_path / "SHA256SUMS").write_text("".join(checksum_lines))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_runtime = fake_bin / "podman"
    runtime_log = tmp_path / "runtime.log"
    fake_runtime.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_RUNTIME_LOG\"\n"
        "exit 0\n"
    )
    fake_runtime.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CONTAINER_RUNTIME": "podman",
        "FAKE_RUNTIME_LOG": str(runtime_log),
    }

    result = subprocess.run(
        [str(installer), "--replace", "--ollama-url", invalid_url],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "URL Ollama invalide" in result.stderr
    assert not runtime_log.exists()

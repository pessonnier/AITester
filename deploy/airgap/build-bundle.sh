#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
OUTPUT_DIR=${OUTPUT_DIR:-"${ROOT_DIR}/dist"}
RUNTIME=${CONTAINER_RUNTIME:-}
VERSION=${VERSION:-$(python3 -c 'import pathlib,sys,tomllib; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])' "${ROOT_DIR}/pyproject.toml" 2>/dev/null || printf 'dev')}
HOST_ARCH=$(uname -m)
case "${HOST_ARCH}" in
  x86_64|amd64) HOST_ARCH=x86_64 ;;
  *) printf 'L’image ROCm GPU prend uniquement en charge x86_64/amd64.\n' >&2; exit 2 ;;
esac
ARCH=${ARCH:-${HOST_ARCH}}
[[ ${ARCH} == amd64 ]] && ARCH=x86_64
IMAGE_REF=${IMAGE_REF:-"ai-tester:${VERSION}"}
GPU_BASE_IMAGE=${GPU_BASE_IMAGE:-"rocm/dev-ubuntu-24.04:7.2.4@sha256:bdc8e61026cbb844ede93d44d2c50055f51ebb2041906b60182bf3bee3139054"}
ARCHIVE_NAME="ai-tester-image-${VERSION}-${ARCH}.tar"
BUNDLE_NAME="ai-tester-airgap-${VERSION}-${ARCH}.tar.gz"

if [[ ! ${VERSION} =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || ! ${ARCH} =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  printf 'VERSION ou ARCH invalide.\n' >&2
  exit 2
fi
if [[ ! ${IMAGE_REF} =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]]; then
  printf 'IMAGE_REF invalide: %s\n' "${IMAGE_REF}" >&2
  exit 2
fi
if [[ ! ${GPU_BASE_IMAGE} =~ @sha256:[a-f0-9]{64}$ ]]; then
  printf 'GPU_BASE_IMAGE doit être épinglée par digest sha256.\n' >&2
  exit 2
fi
if [[ ${ARCH} != "${HOST_ARCH}" ]]; then
  printf 'ARCH=%s ne correspond pas à l’architecture hôte %s.\n' "${ARCH}" "${HOST_ARCH}" >&2
  exit 2
fi

SOURCE_COMMIT=$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || printf 'unknown')
SOURCE_DIRTY=0
if [[ ${SOURCE_COMMIT} == unknown && ${ALLOW_UNVERSIONED:-0} != 1 ]]; then
  printf 'Un dépôt Git est requis pour tracer la source. Utilisez ALLOW_UNVERSIONED=1 pour déroger.\n' >&2
  exit 2
fi
if [[ ${SOURCE_COMMIT} != unknown ]] && [[ -n $(git -C "${ROOT_DIR}" status --porcelain) ]]; then
  SOURCE_DIRTY=1
fi
if ((SOURCE_DIRTY == 1)) && [[ ${ALLOW_DIRTY:-0} != 1 ]]; then
  printf 'Le dépôt contient des modifications. Commitez-les ou utilisez ALLOW_DIRTY=1.\n' >&2
  exit 2
fi
if [[ -z ${RUNTIME} ]]; then
  if command -v podman >/dev/null 2>&1; then
    RUNTIME=podman
  elif command -v docker >/dev/null 2>&1; then
    RUNTIME=docker
  else
    printf 'Podman ou Docker est requis sur la machine connectée.\n' >&2
    exit 1
  fi
fi
if [[ ${RUNTIME} != podman && ${RUNTIME} != docker ]]; then
  printf 'CONTAINER_RUNTIME doit valoir podman ou docker.\n' >&2
  exit 2
fi
command -v "${RUNTIME}" >/dev/null 2>&1 || { printf '%s est introuvable.\n' "${RUNTIME}" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { printf 'sha256sum est requis.\n' >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { printf 'tar est requis.\n' >&2; exit 1; }
LOCK_LINE=$(sha256sum "${ROOT_DIR}/deploy/airgap/requirements.lock")
LOCK_SHA256=${LOCK_LINE%% *}

mkdir -p "${OUTPUT_DIR}"
WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT
BUNDLE_DIR="${WORK_DIR}/ai-tester-airgap"
mkdir -p "${BUNDLE_DIR}"

printf 'Construction de %s avec %s...\n' "${IMAGE_REF}" "${RUNTIME}"
"${RUNTIME}" build \
  --build-arg "GPU_BASE_IMAGE=${GPU_BASE_IMAGE}" \
  --build-arg "SOURCE_COMMIT=${SOURCE_COMMIT}" \
  --build-arg "LOCK_SHA256=${LOCK_SHA256}" \
  --file "${ROOT_DIR}/Containerfile" \
  --tag "${IMAGE_REF}" \
  "${ROOT_DIR}"

IMAGE_METADATA=$("${RUNTIME}" image inspect --format '{{.Architecture}} {{.Id}}' "${IMAGE_REF}") || {
  printf 'Impossible d’inspecter l’image construite.\n' >&2
  exit 1
}
read -r IMAGE_ARCH IMAGE_ID <<< "${IMAGE_METADATA}"
[[ ${IMAGE_ARCH} == amd64 ]] && IMAGE_ARCH=x86_64
[[ ${IMAGE_ID} =~ ^[a-f0-9]{64}$ ]] && IMAGE_ID="sha256:${IMAGE_ID}"
[[ ${IMAGE_ARCH} == "${ARCH}" ]] || {
  printf 'Architecture image inattendue: %s (attendu: %s).\n' "${IMAGE_ARCH}" "${ARCH}" >&2
  exit 1
}
[[ ${IMAGE_ID} =~ ^sha256:[a-f0-9]{64}$ ]] || {
  printf 'Identifiant image invalide: %s\n' "${IMAGE_ID}" >&2
  exit 1
}

printf 'Export de l’image...\n'
if [[ ${RUNTIME} == podman ]]; then
  podman save --format docker-archive --output "${BUNDLE_DIR}/${ARCHIVE_NAME}" "${IMAGE_REF}"
else
  docker save --output "${BUNDLE_DIR}/${ARCHIVE_NAME}" "${IMAGE_REF}"
fi

cp "${ROOT_DIR}/deploy/airgap/install.sh" "${BUNDLE_DIR}/install.sh"
cp "${ROOT_DIR}/deploy/airgap/requirements.lock" "${BUNDLE_DIR}/requirements.lock"
chmod 0755 "${BUNDLE_DIR}/install.sh"
printf 'IMAGE_REF=%s\nIMAGE_ID=%s\nIMAGE_ARCHIVE=%s\nVERSION=%s\nARCH=%s\nGPU_BASE_IMAGE=%s\nLOCK_SHA256=%s\nSOURCE_COMMIT=%s\nSOURCE_DIRTY=%s\n' \
  "${IMAGE_REF}" "${IMAGE_ID}" "${ARCHIVE_NAME}" "${VERSION}" "${ARCH}" "${GPU_BASE_IMAGE}" \
  "${LOCK_SHA256}" "${SOURCE_COMMIT}" "${SOURCE_DIRTY}" > "${BUNDLE_DIR}/MANIFEST"
(
  cd "${BUNDLE_DIR}"
  sha256sum "${ARCHIVE_NAME}" MANIFEST install.sh requirements.lock > SHA256SUMS
)

tar -C "${WORK_DIR}" -czf "${OUTPUT_DIR}/${BUNDLE_NAME}" ai-tester-airgap
(
  cd "${OUTPUT_DIR}"
  sha256sum "${BUNDLE_NAME}" > "${BUNDLE_NAME}.sha256"
)
printf 'Bundle créé: %s\n' "${OUTPUT_DIR}/${BUNDLE_NAME}"
printf 'Checksum externe: %s\n' "${OUTPUT_DIR}/${BUNDLE_NAME}.sha256"
printf 'Copiez ce fichier dans la zone isolée, extrayez-le, puis lancez ./install.sh.\n'

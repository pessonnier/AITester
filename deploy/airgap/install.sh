#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

RUNTIME=${CONTAINER_RUNTIME:-}
PORT=${AI_TESTER_PORT:-5000}
BIND_ADDRESS=${AI_TESTER_BIND_ADDRESS:-127.0.0.1}
NAME=${AI_TESTER_CONTAINER_NAME:-ai-tester}
OLLAMA_URL=${OLLAMA_BASE_URL:-}
START_CONTAINER=1
REPLACE_EXISTING=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --runtime podman|docker  Moteur de conteneurs à utiliser
  --port PORT              Port HTTP publié (défaut: 5000)
  --bind-address IPV4      Adresse d'écoute (défaut: 127.0.0.1)
  --name NAME              Nom du conteneur (défaut: ai-tester)
  --ollama-url URL         URL Ollama utilisée au démarrage
  --replace                Remplacer un conteneur de même nom
  --no-start               Charger l'image sans démarrer le conteneur
  -h, --help               Afficher cette aide
EOF
}

validate_ollama_url() {
  local url=$1 authority host path port rest label octet
  local -a host_parts
  local url_pattern='^https?://([^/]+)(/.*)?$'
  local authority_pattern='^([^:]+)(:([0-9]{1,5}))?$'
  local dns_label_pattern='^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$'

  [[ ${url} != *[[:space:][:cntrl:]]* ]] || return 1
  [[ ${url} != *"?"* && ${url} != *"#"* ]] || return 1
  [[ ${url} =~ ${url_pattern} ]] || return 1
  authority=${BASH_REMATCH[1]}
  path=${BASH_REMATCH[2]:-}
  [[ ${authority} != *"@"* && ${authority} =~ ${authority_pattern} ]] || return 1
  host=${BASH_REMATCH[1]}
  port=${BASH_REMATCH[3]:-}
  if [[ -n ${port} ]] && ! ((10#${port} >= 1 && 10#${port} <= 65535)); then
    return 1
  fi

  IFS=. read -r -a host_parts <<< "${host}"
  if [[ ${host} =~ ^[0-9.]+$ ]]; then
    ((${#host_parts[@]} == 4)) || return 1
    for octet in "${host_parts[@]}"; do
      [[ ${octet} =~ ^[0-9]{1,3}$ ]] && ((10#${octet} <= 255)) || return 1
    done
  else
    ((${#host} <= 253)) && [[ ${host} != .* && ${host} != *. ]] || return 1
    for label in "${host_parts[@]}"; do
      ((${#label} <= 63)) && [[ ${label} =~ ${dns_label_pattern} ]] || return 1
    done
  fi

  rest=${path}
  while [[ ${rest} == *%* ]]; do
    rest=${rest#*%}
    [[ ${rest:0:2} =~ ^[0-9A-Fa-f]{2}$ ]] || return 1
    rest=${rest:2}
  done
  return 0
}

while (($#)); do
  case "$1" in
    --runtime) RUNTIME=${2:?Valeur manquante pour --runtime}; shift 2 ;;
    --port) PORT=${2:?Valeur manquante pour --port}; shift 2 ;;
    --bind-address) BIND_ADDRESS=${2:?Valeur manquante pour --bind-address}; shift 2 ;;
    --name) NAME=${2:?Valeur manquante pour --name}; shift 2 ;;
    --ollama-url) OLLAMA_URL=${2:?Valeur manquante pour --ollama-url}; shift 2 ;;
    --replace) REPLACE_EXISTING=1; shift ;;
    --no-start) START_CONTAINER=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Option inconnue: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ ${PORT} =~ ^[0-9]{1,5}$ ]] && ((PORT >= 1 && PORT <= 65535)) || { printf 'Port invalide: %s\n' "${PORT}" >&2; exit 2; }
[[ ${NAME} =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { printf 'Nom de conteneur invalide: %s\n' "${NAME}" >&2; exit 2; }
IFS=. read -r -a BIND_OCTETS <<< "${BIND_ADDRESS}"
if ((${#BIND_OCTETS[@]} != 4)); then
  printf 'Adresse IPv4 invalide: %s\n' "${BIND_ADDRESS}" >&2
  exit 2
fi
for octet in "${BIND_OCTETS[@]}"; do
  [[ ${octet} =~ ^[0-9]{1,3}$ ]] && ((10#${octet} <= 255)) || { printf 'Adresse IPv4 invalide: %s\n' "${BIND_ADDRESS}" >&2; exit 2; }
done

command -v sha256sum >/dev/null 2>&1 || { printf 'sha256sum est requis.\n' >&2; exit 1; }
sha256sum -c SHA256SUMS

IMAGE_REF=
IMAGE_ARCHIVE=
while IFS='=' read -r key value; do
  case "${key}" in
    IMAGE_REF) IMAGE_REF=${value} ;;
    IMAGE_ARCHIVE) IMAGE_ARCHIVE=${value} ;;
  esac
done < MANIFEST
[[ ${IMAGE_REF} =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]] || { printf 'IMAGE_REF invalide dans MANIFEST.\n' >&2; exit 1; }
[[ ${IMAGE_ARCHIVE} =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.tar$ ]] || { printf 'IMAGE_ARCHIVE invalide dans MANIFEST.\n' >&2; exit 1; }
[[ -f ${IMAGE_ARCHIVE} ]] || { printf 'Archive image absente: %s\n' "${IMAGE_ARCHIVE}" >&2; exit 1; }

if [[ -z ${RUNTIME} ]]; then
  if command -v podman >/dev/null 2>&1; then
    RUNTIME=podman
  elif command -v docker >/dev/null 2>&1; then
    RUNTIME=docker
  else
    printf 'Podman ou Docker est requis dans la zone isolée.\n' >&2
    exit 1
  fi
fi
[[ ${RUNTIME} == podman || ${RUNTIME} == docker ]] || { printf '--runtime doit valoir podman ou docker.\n' >&2; exit 2; }
command -v "${RUNTIME}" >/dev/null 2>&1 || { printf '%s est introuvable.\n' "${RUNTIME}" >&2; exit 1; }

if [[ -z ${OLLAMA_URL} ]]; then
  if [[ ${RUNTIME} == podman ]]; then
    OLLAMA_URL=http://host.containers.internal:11434
  else
    OLLAMA_URL=http://host.docker.internal:11434
  fi
fi
validate_ollama_url "${OLLAMA_URL}" || { printf 'URL Ollama invalide: %s\n' "${OLLAMA_URL}" >&2; exit 2; }

EXISTING_CONTAINER=0
if ((START_CONTAINER == 1)) && "${RUNTIME}" container inspect "${NAME}" >/dev/null 2>&1; then
  if ((REPLACE_EXISTING == 0)); then
    printf 'Le conteneur %s existe déjà. Utilisez --replace pour le remplacer.\n' "${NAME}" >&2
    exit 2
  fi
  EXISTING_CONTAINER=1
fi

printf 'Chargement de %s avec %s...\n' "${IMAGE_REF}" "${RUNTIME}"
"${RUNTIME}" load -i "$IMAGE_ARCHIVE"

if ((START_CONTAINER == 0)); then
  printf 'Image chargée sans démarrage: %s\n' "${IMAGE_REF}"
  exit 0
fi

if ((EXISTING_CONTAINER == 1)); then
  "${RUNTIME}" rm --force "${NAME}" >/dev/null
fi

RUN_ARGS=(
  run --detach
  --pull=never
  --name "${NAME}"
  --restart unless-stopped
  --publish "${BIND_ADDRESS}:${PORT}:5000"
  --volume ai-tester-data:/data
  --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=64m
  --cap-drop=ALL
  --security-opt=no-new-privileges
  --env "OLLAMA_BASE_URL=${OLLAMA_URL}"
  --env AI_TESTER_ALLOWED_DESTINATIONS=/data/allowed_destinations.json
)
if [[ ${RUNTIME} == docker ]]; then
  RUN_ARGS+=(--add-host=host.docker.internal:host-gateway)
fi

CONTAINER_ID=$("${RUNTIME}" "${RUN_ARGS[@]}" "${IMAGE_REF}")
printf 'Conteneur démarré: %s\n' "${CONTAINER_ID}"

for ((attempt = 1; attempt <= 30; attempt++)); do
  if "${RUNTIME}" exec "${NAME}" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/', timeout=2).read(1)" >/dev/null 2>&1; then
    printf 'AI Tester est prêt sur http://%s:%s\n' "${BIND_ADDRESS}" "${PORT}"
    exit 0
  fi
  sleep 1
done

printf 'AI Tester n’est pas devenu prêt. Derniers journaux:\n' >&2
"${RUNTIME}" logs --tail 50 "${NAME}" >&2 || true
exit 1

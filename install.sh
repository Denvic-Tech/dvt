#!/bin/bash
# DVT installation_manager bootstrap.
# Starts only the public web installer; no DVT license or registry credentials are required.

set -euo pipefail

RAW_STORAGE_URL="${RAW_STORAGE_URL:-https://raw.distribution.denvic.tech}"
CONTAINER_REGISTRY_URL="${CONTAINER_REGISTRY_URL:-cr.distribution.denvic.tech}"
INSTALLATION_MANAGER_IMAGE="${INSTALLATION_MANAGER_IMAGE:-cr.distribution.denvic.tech/dvt/installation_manager:latest}"
COMPOSE_FILE_URL="${COMPOSE_FILE_URL:-$RAW_STORAGE_URL/dvt/installation_manager/docker-compose.yaml}"
DVT_LIB_DIR="${DVT_LIB_DIR:-/var/lib/dvt}"
DVT_INSTALLATION_MANAGER_EXTERNAL_PORT="${DVT_INSTALLATION_MANAGER_EXTERNAL_PORT:-8888}"
NETWORK_NAME="dvt-net"
NON_INTERACTIVE=false

EMOJI_ROCKET="🚀"; EMOJI_OK="✅"; EMOJI_WARN="⚠️"; EMOJI_ERR="❌"; EMOJI_GLOBE="🌐"; EMOJI_GEAR="⚙️"

if [ "$EUID" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  echo "$EMOJI_ERR нужен root или sudo, а sudo не установлен." >&2
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case $1 in
    -n|--non-interactive) NON_INTERACTIVE=true; shift ;;
    --dir)          DVT_LIB_DIR="$2"; shift 2 ;;
    --port)         DVT_INSTALLATION_MANAGER_EXTERNAL_PORT="$2"; shift 2 ;;
    --image)        INSTALLATION_MANAGER_IMAGE="$2"; shift 2 ;;
    --registry)     CONTAINER_REGISTRY_URL="$2"; shift 2 ;;
    --compose-url)  COMPOSE_FILE_URL="$2"; shift 2 ;;
    *) echo "$EMOJI_WARN Неизвестный аргумент: $1"; shift ;;
  esac
done

ask() {
    local prompt="${1-}" default="${2-}" value=""
    if [ "$NON_INTERACTIVE" = true ]; then
        printf '%s\n' "$default"
        return
    fi
    [ -n "$prompt" ] && printf "%s" "$prompt" >&2
    [ -n "$default" ] && printf " [%s]" "$default" >&2
    printf " > " >&2
    IFS= read -r value
    [ -z "$value" ] && value="$default"
    printf '%s\n' "$value"
}

detect_compose_cmd() {
    if $SUDO docker compose version >/dev/null 2>&1; then echo "docker compose"; return 0; fi
    if command -v docker-compose >/dev/null 2>&1 && $SUDO docker-compose version >/dev/null 2>&1; then
        echo "docker-compose"; return 0
    fi
    return 1
}

if [ "$NON_INTERACTIVE" = false ]; then
    echo ""
    echo "$EMOJI_ROCKET  DVT — public web installer"
    echo "---------------------------------------------"
fi

command -v docker >/dev/null 2>&1 || { echo "$EMOJI_ERR Docker не найден."; exit 1; }
COMPOSE_CMD="$(detect_compose_cmd || true)"
[ -n "$COMPOSE_CMD" ] || { echo "$EMOJI_ERR Docker Compose не найден."; exit 1; }
echo "$EMOJI_OK Docker и Docker Compose доступны."

DVT_LIB_DIR="$(ask 'Каталог данных DVT' "$DVT_LIB_DIR")"
$SUDO mkdir -p "$DVT_LIB_DIR"
DVT_INSTALLATION_MANAGER_EXTERNAL_PORT="$(ask 'Внешний порт веб-установщика' "$DVT_INSTALLATION_MANAGER_EXTERNAL_PORT")"

COMPOSE_FILE="$DVT_LIB_DIR/docker-compose.yaml"
if [ -f "$COMPOSE_FILE" ]; then
    echo "$EMOJI_OK Найден docker-compose.yaml в $DVT_LIB_DIR."
else
    echo "Скачивание $COMPOSE_FILE_URL ..."
    $SUDO bash -c "curl -fsSL \"$COMPOSE_FILE_URL\" -o \"$COMPOSE_FILE\""
    echo "$EMOJI_OK docker-compose.yaml сохранён: $COMPOSE_FILE"
fi

if ! $SUDO docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    $SUDO docker network create "$NETWORK_NAME" >/dev/null
fi

ENV_FILE="$DVT_LIB_DIR/.env.installation_manager"
$SUDO tee "$ENV_FILE" > /dev/null <<EOF
DVT_LIB_DIR=${DVT_LIB_DIR}
DVT_INSTALLATION_MANAGER_IMAGE=${INSTALLATION_MANAGER_IMAGE}
DVT_INSTALLATION_MANAGER_EXTERNAL_PORT=${DVT_INSTALLATION_MANAGER_EXTERNAL_PORT}
CONTAINER_REGISTRY_URL=${CONTAINER_REGISTRY_URL}
RAW_STORAGE_URL=${RAW_STORAGE_URL}
COMPOSE_PROJECT_NAME=dvt
EOF

echo "$EMOJI_ROCKET Запуск installation_manager с anonymous image pull..."
max_attempts=3; attempt=1; rc=1; last_error=""
while [ "$attempt" -le "$max_attempts" ]; do
  set +e
  up_output="$($SUDO $COMPOSE_CMD --project-name dvt -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans --pull always 2>&1)"
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then break; fi
  last_error="$up_output"
  echo "$EMOJI_WARN Попытка $attempt/$max_attempts не удалась (код $rc)."
  echo "$up_output" | tail -n 100 || true
  [ "$attempt" -lt "$max_attempts" ] && sleep $((attempt * 10))
  attempt=$((attempt + 1))
done

if [ "$rc" -ne 0 ]; then
  echo "$EMOJI_ERR Не удалось запустить installation_manager."
  echo "$last_error" | tail -n 200 || true
  exit "$rc"
fi

echo "$EMOJI_OK installation_manager запущен."
echo "$EMOJI_GLOBE http://localhost:${DVT_INSTALLATION_MANAGER_EXTERNAL_PORT}"
echo "Лицензионный ключ DVT не требуется."

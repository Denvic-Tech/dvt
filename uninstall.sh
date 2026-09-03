#!/bin/bash
# DVT uninstall script

set -e

# ---------- Переменные ----------

DVT_LIB_DIR='/var/lib/dvt'
FORCE_YES=false

# ---------- Эмодзи ----------

EMOJI_TRASH="🗑️"
EMOJI_WARN="⚠️"
EMOJI_ERR="❌"
EMOJI_OK="✅"
EMOJI_STOP="🛑"

# ---------- Парсинг аргументов ----------

while [[ $# -gt 0 ]]; do
  case $1 in
    -y|--yes)
      FORCE_YES=true
      shift
      ;;
    --dir)
      DVT_LIB_DIR="$2"
      shift 2
      ;;
    *)
      echo "Неизвестный аргумент: $1"
      exit 1
      ;;
  esac
done

# ---------- Утилиты ----------

detect_compose_cmd() {
    if sudo docker compose version >/dev/null 2>&1; then
        echo "docker compose"
        return 0
    fi
    if command -v sudo docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
        return 0
    fi
    return 1
}

ask_confirm() {
    local prompt="$1"
    if [ "$FORCE_YES" = true ]; then
        return 0
    fi

    echo -n "$prompt [y/N]: "
    read -r response
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ---------- Начало работы ----------

echo ""
echo "$EMOJI_TRASH  Скрипт удаления DVT"
echo "---------------------------------------------"
echo "Будет удалено:"
echo "  1. Все Docker контейнеры DVT"
echo "  2. Все Docker образы, связанные с DVT"
echo "  3. Все Docker тома (Volumes)"
echo "  4. Директория с данными и конфигами: $DVT_LIB_DIR"
echo ""

if [ ! -d "$DVT_LIB_DIR" ]; then
    echo "$EMOJI_WARN Директория $DVT_LIB_DIR не найдена."
    echo "Возможно, DVT уже удален или установлен в другом месте (используйте --dir)."

    if ! ask_confirm "Вы хотите продолжить и попытаться очистить остатки Docker?"; then
        echo "Отмена."
        exit 0
    fi
else
    if ! ask_confirm "$EMOJI_WARN ВНИМАНИЕ: Это действие необратимо. Удалить DVT?"; then
        echo "Отмена."
        exit 0
    fi
fi

# ---------- Очистка Docker ----------

echo ""
echo "$EMOJI_STOP  Остановка и удаление контейнеров..."

COMPOSE_FILE="$DVT_LIB_DIR/docker-compose.yaml"
COMPOSE_CMD="$(detect_compose_cmd || true)"

if [ -n "$COMPOSE_CMD" ] && [ -f "$COMPOSE_FILE" ]; then
    # Переходим в папку, чтобы контекст docker compose был верным
    cd "$DVT_LIB_DIR" || true

    # down: останавливает и удаляет контейнеры
    # -v: удаляет named volumes, объявленные в section volumes
    # --rmi all: удаляет все образы, используемые любым сервисом
    # --remove-orphans: удаляет контейнеры, не описанные в compose файле
    sudo $COMPOSE_CMD down -v --rmi all --remove-orphans || {
        echo "$EMOJI_WARN Ошибка при выполнении docker compose down. Продолжаем удаление файлов..."
    }
    echo "$EMOJI_OK  Docker ресурсы очищены."
else
    echo "$EMOJI_WARN Не найден docker-compose.yaml или команда docker compose."
    echo "Пропуск очистки Docker через Compose. Если контейнеры запущены, удалите их вручную."
fi

# ---------- Удаление файлов ----------

echo ""
echo "$EMOJI_TRASH  Удаление файлов ($DVT_LIB_DIR)..."

if [ -d "$DVT_LIB_DIR" ]; then
    sudo rm -rf "$DVT_LIB_DIR"
    echo "$EMOJI_OK  Директория удалена."
else
    echo "$EMOJI_OK  Директория уже отсутствует."
fi

# ---------- Финал ----------

echo ""
echo "$EMOJI_OK  DVT успешно удален из системы."
echo ""
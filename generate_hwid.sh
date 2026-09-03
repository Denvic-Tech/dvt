#!/usr/bin/env bash
set -e

# Папка и файл HWID
HWID_DIR="$(dirname "$0")/../hwid"
HWID_FILE="$HWID_DIR/hwid.id"

mkdir -p "$HWID_DIR"

# -----------------------------
# Если файл уже существует и НЕ пустой → вернуть как есть
# -----------------------------
if [[ -f "$HWID_FILE" ]]; then
    EXISTING=$(cat "$HWID_FILE" | tr -d '[:space:]')

    if [[ -n "$EXISTING" ]]; then
        echo "Существующий HWID найден: $EXISTING"
        exit 0
    fi
fi

# -----------------------------
# Определяем ОС и получаем machine-id
# -----------------------------
MACHINE_FINGERPRINT=""

OS=$(uname | tr '[:upper:]' '[:lower:]')

if [[ "$OS" == "linux" ]]; then
    if [[ -f "/etc/machine-id" ]]; then
        MACHINE_FINGERPRINT=$(cat /etc/machine-id)
    elif [[ -f "/proc/sys/kernel/random/boot_id" ]]; then
        MACHINE_FINGERPRINT=$(cat /proc/sys/kernel/random/boot_id)
    fi

elif [[ "$OS" == "darwin" ]]; then
    # macOS → serial number
    MACHINE_FINGERPRINT=$(system_profiler SPHardwareDataType | awk '/Serial/ {print $4}')
fi

# -----------------------------
# Генерация уникального fallback
# -----------------------------
if [[ -z "$MACHINE_FINGERPRINT" ]]; then
    echo "Machine ID не найден, используем уникальный fallback"

    if command -v uuidgen >/dev/null 2>&1; then
        MACHINE_FINGERPRINT=$(uuidgen)
    else
        MACHINE_FINGERPRINT=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' ')
    fi
fi

# -----------------------------
# Генерация SHA256
# -----------------------------
HWID=$(echo -n "$MACHINE_FINGERPRINT" | sha256sum | awk '{print $1}')

# -----------------------------
# Сохраняем в файл
# -----------------------------
echo "$HWID" > "$HWID_FILE"

echo "HWID generated: $HWID"

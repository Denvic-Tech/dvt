#!/usr/bin/env bash
# Run on a dedicated Linux test VM as root. Credentials generated here are test-only.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
MODE="$1"
if [[ "$MODE" == arm ]]; then
    WORK="$(mktemp -d /var/tmp/dvt-stage03-test.XXXXXXXX)"
    trap 'echo "Fixture directory: $WORK" >&2' EXIT
    PROJECT="dvt-stage03-$(basename "$WORK" | cut -d. -f2 | tr '[:upper:]' '[:lower:]')"
    read -r REG_PORT WEB_PORT < <(python3 - <<'PY'
import socket
with socket.socket() as first, socket.socket() as second:
    for sock in (first, second):
        sock.bind(("127.0.0.1", 0))
    print(first.getsockname()[1], second.getsockname()[1])
PY
)
    docker run -d --name "$PROJECT-registry" -p "127.0.0.1:$REG_PORT:5000" registry:2 >/dev/null
    REPO="127.0.0.1:$REG_PORT/dvt-stage03/manager"
    printf '%s\n' "$REPO" > "$WORK/repository"
    docker build -f "$ROOT/services/installation_manager/Dockerfile" -t "$REPO:old" "$ROOT"
    cat > "$WORK/gate" <<'SH'
#!/bin/sh
set -eu
if [ "$1" = candidate-web ]; then
  while [ ! -f "$2/.bootstrap/test-allow-ready" ]; do sleep 1; done
fi
exec python -m services.installation_manager "$@"
SH
    chmod 0755 "$WORK/gate"
    cat > "$WORK/Dockerfile" <<EOF
FROM $REPO:old
COPY gate /stage03-fixture-gate
ENTRYPOINT ["/stage03-fixture-gate"]
EOF
    docker build -t "$REPO:new" "$WORK"
    docker push "$REPO:old" >/dev/null
    docker push "$REPO:new" >/dev/null
    PREVIOUS="$(docker image inspect --format '{{index .RepoDigests 0}}' "$REPO:old")"
    TARGET="$(docker image inspect --format '{{index .RepoDigests 0}}' "$REPO:new")"
    openssl req -x509 -newkey rsa:2048 -noenc -keyout "$WORK/key.pem" \
        -out "$WORK/cert.pem" -days 2 -subj '/CN=localhost' \
        -addext 'subjectAltName=DNS:localhost' 2>/dev/null
    ARGS=(--dir "$WORK/data" --port "$WEB_PORT" --project "$PROJECT"
          --manager "$PREVIOUS" --executor "$PREVIOUS" --candidate "$TARGET"
          --cert "$WORK/cert.pem" --ca "$WORK/cert.pem" --key "$WORK/key.pem"
          --non-interactive)
    if [[ "$(docker info --format '{{json .DriverStatus}}')" == *io.containerd.snapshotter.v1* ]]; then
        ARGS+=(--containerd-root "${DVT_STAGE03_CONTAINERD_ROOT:-/var/lib/containerd}")
    fi
    bash "$ROOT/install.sh" --beta "${ARGS[@]}" > "$WORK/first.out"
    bash "$ROOT/install.sh" --beta "${ARGS[@]}" > "$WORK/repeat.out"
    diff <(head -n 2 "$WORK/first.out") "$WORK/repeat.out"
    if bash "$ROOT/install.sh" --beta --dir "$WORK/collision" --project "$PROJECT" --non-interactive; then
        echo 'Unexpected success for Compose project collision' >&2
        exit 1
    fi
    test ! -e "$WORK/collision"
    if bash "$ROOT/install.sh" --beta "${ARGS[@]}" --port "$(( WEB_PORT == 65535 ? 65534 : WEB_PORT + 1 ))"; then
        echo 'Unexpected success for a changed HTTPS port' >&2
        exit 1
    fi
    LC_ALL=C tr -cd '\11\12\15\40-\176' < "$WORK/repeat.out"
    printf '%s\n' "$PROJECT" > "$WORK/project"
    printf '%s\n' "$WEB_PORT" > "$WORK/port"
    printf '%s\n' "$PREVIOUS" > "$WORK/previous"
    printf '%s\n' "$TARGET" > "$WORK/target"
    cat /proc/sys/kernel/random/boot_id > "$WORK/before-boot"
    python3 "$(dirname "$0")/handoff_http.py" arm "$WORK"
elif [[ "$MODE" == verify ]]; then
    WORK="$2"
    test -e "$WORK/reboot.ready"
    test "$(cat "$WORK/before-boot")" != "$(cat /proc/sys/kernel/random/boot_id)"
    PROJECT="$(cat "$WORK/project")"
    systemctl show "dvt-bootstrap-$PROJECT.service" -p Result -p ExecMainStatus
    test "$(systemctl show "dvt-bootstrap-$PROJECT.service" -p Result --value)" = success
    touch "$WORK/data/.bootstrap/test-allow-ready"
    python3 "$(dirname "$0")/handoff_http.py" verify "$WORK"
elif [[ "$MODE" == verify-fallback ]]; then
    WORK="$2"
    test -e "$WORK/reboot.ready"
    test "$(cat "$WORK/before-boot")" = "$(cat /proc/sys/kernel/random/boot_id)"
    python3 "$(dirname "$0")/handoff_http.py" verify-fallback "$WORK"
else
    echo 'Expected arm, verify or verify-fallback' >&2
    exit 2
fi

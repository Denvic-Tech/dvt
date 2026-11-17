#!/usr/bin/env bash
# Removes one named, root-owned handoff smoke fixture from the dedicated test VM.
set -euo pipefail
WORK="$(realpath -- "$1")"
[[ "$WORK" =~ ^/var/tmp/dvt-stage03-test\.[a-zA-Z0-9]{8}$ ]]
[[ -d "$WORK" && "$(stat -c '%u:%a' "$WORK")" == 0:700 ]]
PROJECT="dvt-stage03-$(basename "$WORK" | cut -d. -f2 | tr '[:upper:]' '[:lower:]')"
DATA="$WORK/data"
UNIT="dvt-bootstrap-$PROJECT.service"
UNIT_FILE="/etc/systemd/system/$UNIT"

if [[ -e "$UNIT_FILE" ]]; then
    grep -Fxq "ExecStart=/usr/bin/python3 $DATA/.bootstrap/host_bootstrap.py resume --dir $DATA" "$UNIT_FILE"
    systemctl disable --now "$UNIT" >/dev/null
    rm -- "$UNIT_FILE"
    systemctl daemon-reload
fi
while IFS= read -r executor; do
    [[ -n "$executor" ]] || continue
    if docker inspect --format '{{range .Mounts}}{{println .Source}}{{end}}' "$executor" |
        grep -Fxq "$DATA"; then
        docker rm -f -- "$executor" >/dev/null
    fi
done < <(docker ps -aq --filter 'label=dvt.executor.instance')

COMPOSE="$DATA/.bootstrap/bootstrap.compose.yaml"
if [[ -f "$COMPOSE" ]]; then
    docker compose --project-name "$PROJECT" --project-directory "$DATA" \
        --env-file /dev/null --file "$COMPOSE" down
fi
REGISTRY="$PROJECT-registry"
if docker inspect "$REGISTRY" >/dev/null 2>&1; then
    [[ "$(docker inspect --format '{{.Config.Image}}' "$REGISTRY")" == registry:2 ]]
    docker rm -fv -- "$REGISTRY" >/dev/null
fi
if [[ -f "$WORK/repository" ]]; then
    REPO="$(cat "$WORK/repository")"
    [[ "$REPO" =~ ^127\.0\.0\.1:[0-9]+/dvt-stage03/manager$ ]]
    for tag in old new; do
        if docker image inspect "$REPO:$tag" >/dev/null 2>&1; then
            docker image rm "$REPO:$tag" >/dev/null
        fi
    done
fi
rm -rf --one-file-system -- "$WORK"
printf 'Removed isolated fixture %s\n' "$PROJECT"

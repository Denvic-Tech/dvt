#!/usr/bin/env bash
# Remove a confirmed local Compose project. Data removal is a separate opt-in.
set -euo pipefail

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

dir=/var/lib/dvt
project=
yes=false
plan_only=false
delete_data=false
confirmation=
args=("$@")
while (($#)); do
    case "$1" in
        --dir|--project|--confirm-data)
            (($# >= 2)) || fail "Нет значения для $1."
            case "$1" in
                --dir) dir=$2 ;;
                --project) project=$2 ;;
                --confirm-data) confirmation=$2 ;;
            esac
            shift 2
            ;;
        --plan) plan_only=true; shift ;;
        --delete-data) delete_data=true; shift ;;
        -y|--yes) yes=true; shift ;;
        *) fail "Неизвестный аргумент: $1." ;;
    esac
done

if ((EUID)); then
    [[ -f "$0" ]] || fail "Запустите сохранённый скрипт от root."
    exec sudo bash "$(realpath -e -- "$0")" "${args[@]}"
fi

[[ "$dir" =~ ^/[a-zA-Z0-9_./-]+$ && "$dir" != / && -d "$dir" ]] ||
    fail "Нужен абсолютный каталог установленного DVT."
[[ "$(realpath -e -- "$dir")" = "$dir" && -f "$dir/docker-compose.yaml" &&
    ! -L "$dir/docker-compose.yaml" && -f "$dir/.env" && ! -L "$dir/.env" ]] ||
    fail "Не найден канонический каталог с рабочими файлами DVT."
[[ "$(stat -c %u -- "$dir")" = 0 ]] || fail "Каталог DVT должен принадлежать root."

if [[ -e "$dir/.bootstrap/host.json" ]]; then
    saved=$(python3 - "$dir" <<'PY'
import json
import re
import stat
import sys
from pathlib import Path

base = Path(sys.argv[1])
path = base / ".bootstrap" / "host.json"
info = path.lstat()
if (
    path.resolve() != path or not stat.S_ISREG(info.st_mode)
    or info.st_uid or info.st_mode & 0o077 or info.st_size > 65536
):
    sys.exit("Небезопасный файл конфигурации DVT.")
config = json.loads(path.read_text())
project, backup = config["project"], config["backup"]
if (
    config["data"] != str(base) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", project)
    or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", backup) or str(Path(backup).resolve()) != backup
    or backup == str(base) or base.is_relative_to(backup)
):
    sys.exit("Конфигурация не подтверждает выбранный каталог DVT.")
print(project)
print(backup)
PY
    )
    saved_project=${saved%%$'\n'*}
    backup=${saved#*$'\n'}
    [[ -z "$project" || "$project" = "$saved_project" ]] || fail "Проект не соответствует identity."
    project=$saved_project
else
    project=${project:-dvt}
    backup="$dir/backup"
fi
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]] || fail "Недопустимое имя проекта."

docker_local() {
    env -u DOCKER_CONTEXT -u DOCKER_HOST -u DOCKER_TLS_VERIFY -u DOCKER_CERT_PATH \
        docker --host unix:///var/run/docker.sock "$@"
}

containers=$(docker_local container ls --all --quiet --no-trunc --filter "label=com.docker.compose.project=$project")
volumes=$(docker_local volume ls --quiet --filter "label=com.docker.compose.project=$project")
networks=$(docker_local network ls --quiet --no-trunc --filter "label=com.docker.compose.project=$project")
ids=()
volume_names=()
network_ids=()
unit="/etc/systemd/system/dvt-bootstrap-$project.service"
if [[ -e "$unit" ]]; then
    [[ -f "$unit" && ! -L "$unit" ]] || fail "Не удалось подтвердить unit DVT."
    if ! grep -Fxq "ExecStart=/usr/bin/python3 $dir/.bootstrap/host_bootstrap.py resume --dir $dir" "$unit"; then
        fail "Unit DVT относится к другому экземпляру."
    fi
fi
if [[ -n "$containers" ]]; then
    mapfile -t ids <<<"$containers"
    for id in "${ids[@]}"; do
        owner=$(docker_local container inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$id")
        [[ "$owner" = "$dir" ]] || fail "У контейнера проекта другой рабочий каталог."
    done
elif [[ ! -f "$dir/.bootstrap/host.json" ]]; then
    # With no identity or containers, refuse project-level mutations of volumes and networks.
    volumes=
    networks=
fi
if [[ -n "$volumes" ]]; then mapfile -t volume_names <<<"$volumes"; fi
if [[ -n "$networks" ]]; then mapfile -t network_ids <<<"$networks"; fi

printf 'План удаления DVT из проекта %s\n' "$project"
printf 'Контейнеры (%s), сети проекта (%s)\n' "${#ids[@]}" "${#network_ids[@]}"
for id in "${ids[@]}"; do printf '  контейнер %s\n' "$id"; done
for id in "${network_ids[@]}"; do printf '  сеть %s\n' "$id"; done
if [[ -e "$unit" ]]; then printf '  служба %s\n' "$unit"; fi
if $delete_data; then
    printf 'План удаления данных\n  каталог %s\n' "$dir"
    for volume in "${volume_names[@]}"; do printf '  том %s\n' "$volume"; done
    if [[ "$backup" = "$dir/"* ]]; then
        printf '  каталог копий внутри удаляемых данных %s\n' "$backup"
    else
        printf '  внешние копии сохраняются в %s\n' "$backup"
    fi
else
    printf 'Данные и конфигурация сохраняются в %s, копии в %s\n' "$dir" "$backup"
    for volume in "${volume_names[@]}"; do printf '  сохраняемый том %s\n' "$volume"; done
fi
if $plan_only; then exit 0; fi
if ! $yes; then
    read -r -p 'Выполнить показанный план удаления DVT? [y/N] ' reply
    [[ "$reply" = y || "$reply" = yes ]] || exit 0
fi
if $delete_data; then
    if ! $yes && [[ -z "$confirmation" ]]; then
        read -r -p 'Подтвердите удаление данных полным путём каталога DVT: ' confirmation
    fi
    [[ "$confirmation" = "$dir" ]] ||
        fail "Для удаления данных передайте --confirm-data с точным путём каталога."
    mounts=$(findmnt --noheadings --raw --list --output TARGET)
    while IFS= read -r mountpoint; do
        if [[ "$mountpoint" = "$dir" || "$mountpoint" = "$dir/"* ]]; then
            fail "В каталоге DVT есть смонтированная файловая система."
        fi
    done <<<"$mounts"
fi

journal="$dir/.installation-state/journal.sqlite3"
confirm_inactive() {
    [[ -f "$journal" ]] || return 0
    python3 - "$journal" <<'PY'
import sqlite3
import sys
from pathlib import Path

with sqlite3.connect(Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True) as db:
    if db.execute("SELECT 1 FROM operations WHERE finished_at IS NULL LIMIT 1").fetchone():
        sys.exit("В журнале есть незавершённая операция DVT.")
PY
}
if [[ -e "$journal" ]]; then
    [[ ! -L "$dir/.installation-state" && ! -L "$journal" &&
        ! -L "$dir/.installation-state/executor.lock" ]] || fail "Небезопасный журнал DVT."
    umask 077
    exec 9<>"$dir/.installation-state/executor.lock"
    flock -n -x 9 || fail "Активен исполнитель DVT."
    confirm_inactive
fi
current=$(docker_local container ls --all --quiet --no-trunc --filter "label=com.docker.compose.project=$project")
[[ "$current" = "$containers" ]] || fail "Состав контейнеров изменился. Повторите план."
if [[ -e "$unit" ]]; then
    systemctl disable --now "$(basename -- "$unit")"
    rm -- "$unit"
    systemctl daemon-reload
fi
if (("${#ids[@]}")); then
    docker_local container stop --timeout=30 "${ids[@]}"
    confirm_inactive
    docker_local container rm "${ids[@]}"
fi
if (("${#network_ids[@]}")); then docker_local network rm "${network_ids[@]}"; fi
if $delete_data; then
    for id in $(docker_local container ls --all --quiet --no-trunc); do
        sources=$(docker_local container inspect --format '{{range .Mounts}}{{if eq .Type "bind"}}{{println .Source}}{{end}}{{end}}' "$id")
        while IFS= read -r source; do
            [[ -n "$source" ]] || continue
            if [[ "$source" = "$dir" || "$source" = "$dir/"* || "$dir" = "${source%/}/"* ]]; then
                fail "Данные DVT используются контейнером вне подтверждённого проекта."
            fi
        done <<<"$sources"
    done
    if (("${#volume_names[@]}")); then docker_local volume rm "${volume_names[@]}"; fi
    rm -rf --one-file-system -- "$dir"
fi
printf 'План удаления выполнен.\n'

#!/usr/bin/env bash
# Capture VM facts and image observations without serializing container configuration.
set -Eeuo pipefail

if [[ $# -lt 4 || $# -gt 5 || ! "$1" =~ ^[a-z0-9][a-z0-9_-]{0,63}$ ]]; then
    printf 'Usage: bash capture_vm.sh PROJECT DATA TEMPORARY BACKUP [CONTAINERD_ROOT]\n' >&2
    exit 2
fi

project=$1
printf 'started_utc=%s\n' "$(date -u +%FT%TZ)"
sed -nE '/^(ID|VERSION_ID)=/p' /etc/os-release
printf 'architecture=%s\n' "$(uname -m)"
docker version --format 'docker_server={{.Server.Version}}'
printf 'compose_version=%s\n' "$(docker compose version --short)"
docker info --format 'cpus={{.NCPU}} memory_bytes={{.MemTotal}}'
printf 'project=%s\n' "$project"

filesystem() {
    local role=$1 path=$2
    printf '%s_free_bytes=%s\n' "$role" "$(df --output=avail -B1 -- "$path" | tail -1 | tr -d ' ')"
    printf '%s_free_inodes=%s\n' "$role" "$(df --output=iavail -- "$path" | tail -1 | tr -d ' ')"
}

filesystem docker "$(docker info --format '{{.DockerRootDir}}')"
filesystem data "$2"
filesystem temporary "$3"
filesystem backup "$4"
if [[ $# -eq 5 ]]; then
    filesystem containerd "$5"
fi

containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project")
while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    role=$(docker container inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container")
    state=$(docker container inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$container")
    image=$(docker container inspect --format '{{.Image}}' "$container")
    printf 'service=%s state=%s repo_digests=%s\n' "$role" "$state" \
        "$(docker image inspect --format '{{json .RepoDigests}}' "$image")"
done <<< "$containers"

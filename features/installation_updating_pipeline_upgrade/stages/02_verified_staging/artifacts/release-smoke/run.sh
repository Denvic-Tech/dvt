#!/bin/bash
set -euo pipefail
work=$1
if ! [[ "$work" =~ ^/tmp/dvt-staging-test\.[A-Za-z0-9]{8}$ ]]; then exit 64; fi
suffix=$(basename "$work" | cut -d. -f2 | tr '[:upper:]' '[:lower:]')
tag="dvt-stage02-smoke-$suffix:local"
if docker image inspect "$tag" >/dev/null 2>&1; then exit 65; fi
trap 'docker image rm "$tag" >/dev/null 2>&1 || true' EXIT
install -d -m 0700 "$work/home"
docker build --quiet --tag "$tag" "$work"
docker run --rm --network host --read-only --security-opt no-new-privileges \
    --mount type=bind,source=/usr/bin/docker,target=/usr/local/bin/docker,readonly \
    --mount type=bind,source=/usr/libexec/docker/cli-plugins,target=/usr/libexec/docker/cli-plugins,readonly \
    --mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock,readonly \
    --mount type=bind,source=/etc/os-release,target=/host-os-release,readonly \
    --mount type=bind,source=/var/lib/docker,target=/var/lib/docker,readonly \
    --mount type=bind,source=/var/lib/containerd,target=/var/lib/containerd,readonly \
    --mount "type=bind,source=$work,target=$work" \
    -e "HOME=$work/home" -e "DOCKER_CONFIG=$work/home/.docker" \
    -e DVT_STAGE02_CONTAINERD=/var/lib/containerd \
    -e DVT_STAGE02_OS_RELEASE=/host-os-release \
    -e "DVT_STAGE02_TMP=$work" \
    "$tag"

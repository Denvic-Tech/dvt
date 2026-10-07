#!/usr/bin/env bash
# Shared offline runner. Never downloads Compose, packages, or images.
offline_main() {
    local mode="$1"; shift
    local target="${DVT_LIB_DIR:-/var/lib/dvt}" version="$DVT_ARCHIVE_VERSION"
    local non_interactive=false public_url="" port="" workers="" ai_mcp=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n|--non-interactive) non_interactive=true; shift ;;
            --dir|--version|--public-url|--external-port|--workers)
                [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; return 1; }
                case "$1" in
                    --dir) target="$2" ;;
                    --version) version="$2" ;;
                    --public-url) public_url="$2" ;;
                    --external-port) port="$2" ;;
                    --workers) workers="$2" ;;
                esac
                shift 2 ;;
            --ai-mcp) ai_mcp=true; shift ;;
            --no-ai-mcp) ai_mcp=false; shift ;;
            *) echo "Unknown argument: $1" >&2; return 1 ;;
        esac
    done
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]] || {
        echo "A release version is required; use the generated archive or --version." >&2; return 1;
    }
    if [[ "$DVT_ARCHIVE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ && "$version" != "$DVT_ARCHIVE_VERSION" ]]; then
        echo "Version must match the images and Compose in this archive." >&2; return 1
    fi
    [[ "$target" == /* && "$target" != *$'\n'* && "$target" != *:* ]] || {
        echo "--dir must be an absolute Linux directory." >&2; return 1;
    }
    if [[ "$non_interactive" == false && "$mode" == install && ! -f "$target/.env" ]]; then
        read -r -p "DVT public URL [http://localhost]: " public_url
        public_url="${public_url:-http://localhost}"
    fi
    local -a sudo_cmd=()
    if [[ "$EUID" -ne 0 ]]; then
        command -v sudo >/dev/null || { echo "Run as root or install sudo." >&2; return 1; }
        sudo_cmd=(sudo)
    fi
    [[ -f "$SCRIPT_DIR/docker-compose.yaml" && -f "$SCRIPT_DIR/offline-config.py" ]] || {
        echo "Incomplete offline bundle: Compose or offline-config.py is missing." >&2; return 1;
    }
    if [[ "$mode" == update && ! -f "$target/.env" ]]; then
        echo "Update requires an existing $target/.env." >&2; return 1
    fi
    if ! command -v docker >/dev/null; then
        [[ "$mode" == install ]] || { echo "Docker is required for an update." >&2; return 1; }
        local -a packages=()
        shopt -s nullglob
        packages=("$SCRIPT_DIR"/docker/*/*.deb)
        shopt -u nullglob
        [[ ${#packages[@]} -gt 0 ]] || { echo "No local Docker deb packages." >&2; return 1; }
        "${sudo_cmd[@]}" dpkg -i "${packages[@]}"
        "${sudo_cmd[@]}" systemctl enable --now docker
    fi
    "${sudo_cmd[@]}" docker info >/dev/null
    "${sudo_cmd[@]}" docker compose version >/dev/null
    local -a images=()
    shopt -s nullglob
    images=("$SCRIPT_DIR"/images/*.tar)
    shopt -u nullglob
    [[ ${#images[@]} -gt 0 ]] || { echo "No local image archives." >&2; return 1; }
    local image
    for image in "${images[@]}"; do
        "${sudo_cmd[@]}" docker load -i "$image"
    done
    "${sudo_cmd[@]}" mkdir -p "$target"
    target="$(cd "$target" && pwd)"
    local config_image="cr.distribution.denvic.tech/dvt/installation_manager:$version"
    "${sudo_cmd[@]}" docker image inspect "$config_image" >/dev/null
    local -a config_args=(--mode "$mode" --version "$version" --host-dir "$target")
    [[ -z "$public_url" ]] || config_args+=(--public-url "$public_url")
    [[ -z "$port" ]] || config_args+=(--external-port "$port")
    [[ -z "$workers" ]] || config_args+=(--workers "$workers")
    [[ -z "$ai_mcp" ]] || config_args+=(--ai-mcp "$ai_mcp")
    local result
    result="$("${sudo_cmd[@]}" docker run --rm --pull never --network none \
        --entrypoint python \
        -v "$SCRIPT_DIR:/offline:ro" -v "$target:/dvt-lib" \
        "$config_image" /offline/offline-config.py "${config_args[@]}")"
    local -a settings=()
    mapfile -t settings <<< "$result"
    [[ ${#settings[@]} -eq 3 ]] || { echo "Invalid offline configuration result." >&2; return 1; }
    local -a compose=(docker compose --project-directory "$target" \
        --project-name "${settings[0]}" --env-file "$target/.env")
    local -a services=(postgres valkey orchestrator task-worker project-scheduler gateway ui proxy)
    if [[ "${settings[2]}" == true ]]; then
        compose+=(--profile ai-mcp)
        services+=(dvt-ai-mcp)
    fi
    "${sudo_cmd[@]}" "${compose[@]}" -f "$SCRIPT_DIR/docker-compose.yaml" config --quiet
    local resolved
    resolved="$("${sudo_cmd[@]}" "${compose[@]}" -f "$SCRIPT_DIR/docker-compose.yaml" config --images)"
    while IFS= read -r image; do
        [[ -z "$image" ]] || "${sudo_cmd[@]}" docker image inspect "$image" >/dev/null
    done <<< "$resolved"
    if [[ -f "$target/docker-compose.yaml" && "$SCRIPT_DIR/docker-compose.yaml" != "$target/docker-compose.yaml" ]]; then
        "${sudo_cmd[@]}" cp "$target/docker-compose.yaml" "$target/docker-compose.yaml.bak.$(date +%s%N)"
    fi
    if [[ "$SCRIPT_DIR/docker-compose.yaml" != "$target/docker-compose.yaml" ]]; then
        "${sudo_cmd[@]}" cp "$SCRIPT_DIR/docker-compose.yaml" "$target/docker-compose.yaml"
    fi
    if ! "${sudo_cmd[@]}" docker network inspect dvt-net >/dev/null 2>&1; then
        "${sudo_cmd[@]}" docker network create dvt-net >/dev/null
    fi
    if [[ "${settings[2]}" == false ]]; then
        "${sudo_cmd[@]}" "${compose[@]}" --profile ai-mcp -f "$target/docker-compose.yaml" stop dvt-ai-mcp
    fi
    "${sudo_cmd[@]}" "${compose[@]}" -f "$target/docker-compose.yaml" up -d \
        --pull never --no-build --remove-orphans --scale "task-worker=${settings[1]}" "${services[@]}"
    echo "DVT $version $mode completed using local artifacts."
}

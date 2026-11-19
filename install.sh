#!/bin/sh
# Public, signed DVT installation. The host runs POSIX shell and Docker.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

fail() { printf 'DVT installer: %s\n' "$*" >&2; exit 1; }
public_origin=https://dvt.distribution.denvic.tech
origin=$public_origin
channel= requested_version= explicit_selection=no private_rc=no ca_file= dir= project= port= public_url= containerd=
ask=yes apt=no pair=no
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            printf '%s\n' 'Launch the HTTPS DVT installer' \
                '  --dir PATH --project NAME --port PORT --public-url ORIGIN --containerd-root PATH' \
                '  --non-interactive --install-docker --new-pairing-token' \
                '  --channel stable|rc --version X.Y.Z[-rcN] (first installation)' \
                '  --catalog-origin HTTPS_ORIGIN --catalog-ca FILE --test-rc'
            exit 0 ;;
        -n|--non-interactive) ask=no ;;
        --install-docker) apt=yes ;;
        --new-pairing-token) pair=yes ;;
        --test-rc) private_rc=yes ;;
        --dir|--project|--port|--public-url|--containerd-root|--catalog-origin|--catalog-ca|--channel|--version)
            [ "$#" -ge 2 ] || fail "Missing value for $1"
            case "$1" in
                --dir) dir=$2 ;; --project) project=$2 ;; --port) port=$2 ;;
                --public-url) public_url=$2 ;; --containerd-root) containerd=$2 ;;
                --catalog-origin) origin=${2%/} ;; --catalog-ca) ca_file=$2 ;;
                --channel)
                    [ -z "$channel" ] || fail 'Specify --channel once'
                    case "$2" in stable|rc) channel=$2 ;; *) fail 'Use --channel stable or rc' ;; esac
                    explicit_selection=yes ;;
                --version)
                    [ -z "$requested_version" ] && [ -n "$2" ] || fail 'Specify one release version'
                    requested_version=$2 explicit_selection=yes ;;
            esac
            shift ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done

valid() {
    case "$1" in *'
'*) return 1 ;; esac
    printf '%s\n' "$1" | LC_ALL=C grep -Eq "$2"
}
number='(0|[1-9][0-9]{0,15})'
base_version_pattern="$number\.$number\.$number"
if [ "$private_rc" = yes ]; then
    [ "${channel:-rc}" = rc ] || fail '--test-rc requires the rc channel'
    channel=rc
fi
if [ -n "$requested_version" ]; then
    valid "$requested_version" "^${base_version_pattern}(-?rc[1-9][0-9]{0,15})?$" ||
        fail 'Use --version X.Y.Z or X.Y.Z-rcN'
    case "$requested_version" in
        *rc*) version_channel=rc
              requested_version=$(printf '%s\n' "$requested_version" | sed 's/-\{0,1\}rc/-rc/') ;;
        *) version_channel=stable ;;
    esac
    [ "${channel:-$version_channel}" = "$version_channel" ] || fail 'Version and channel disagree'
    channel=$version_channel
fi
channel=${channel:-stable}

origin_pattern='^https://[a-z0-9.-]+(:[0-9]{1,5})?$'
digest_pattern='^sha256:[0-9a-f]{64}$'
manager_pattern='^[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'
resume_url=$public_url
if [ "$ask" = yes ]; then
    if [ -z "$public_url" ]; then
        # The SSH server address or the source of the default route is local information.
        detected=$(printf '%s\n' "${SSH_CONNECTION:-}" | awk '{print $3}')
        if [ -z "$detected" ]; then
            detected=$(ip -4 route get 192.0.2.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}')
        fi
        if [ -z "$detected" ]; then
            detected=$(hostname -I 2>/dev/null | awk '{print $1}')
        fi
        case "$detected" in *:*) detected="[$detected]" ;; esac
        printf 'DVT host or origin [%s]: ' "${detected:-localhost}" >&2
        IFS= read -r reply </dev/tty || fail 'Use an interactive terminal or --non-interactive'
        public_url=${reply:-${detected:-localhost}}
        if [ -n "$reply" ]; then resume_url=$reply; fi
    fi
    if [ -z "$dir" ]; then
        printf 'Installation directory [/var/lib/dvt]: ' >&2
        IFS= read -r dir </dev/tty || fail 'Use an interactive terminal or --non-interactive'
    fi
fi
dir=${dir:-/var/lib/dvt}
case "$public_url" in ''|http://*|https://*) ;; *) public_url=http://$public_url ;; esac
case "$resume_url" in ''|http://*|https://*) ;; *) resume_url=http://$resume_url ;; esac
public_url_pattern='^https?://([a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(:[0-9]{1,5})?/?$'
[ -z "$public_url" ] || valid "$public_url" "$public_url_pattern" || fail 'Enter an IP, hostname or HTTP(S) origin'
valid "$dir" '^/[a-zA-Z0-9_./-]+$' && [ "$dir" != / ] || fail 'Use a canonical data directory'
[ "$(realpath -m -- "$dir")" = "$dir" ] || fail 'Use a canonical data directory without symlinks'
[ "$(uname -m)" = x86_64 ] || fail 'The installer requires Linux amd64'
os_value() {
    awk -F= -v key="$1" '$1==key { gsub(/"/, "", $2); print $2 }' /etc/os-release
}
distro=$(os_value ID)
version=$(os_value VERSION_ID)
case "$distro:$version" in
    debian:13|ubuntu:24.04) ;;
    *) fail 'The installer supports Debian 13 and Ubuntu 24.04' ;;
esac

# This root-owned shim is persisted atomically with the verified bootstrap.
runtime=$(cat <<'ROOT_SH'
set -eu
umask 077
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL

fail() { printf 'DVT installer: %s\n' "$*" >&2; exit 1; }
valid() {
    case "$1" in *'
'*) return 1 ;; esac
    printf '%s\n' "$1" | grep -Eq "$2"
}
path_check() {
    valid "$1" '^/[a-zA-Z0-9_./-]+$' && [ "$1" != / ] && [ "$(realpath -m -- "$1")" = "$1" ] ||
        fail 'Use canonical absolute paths without symlinks'
    inspect=$1
    while [ "$inspect" != / ]; do
        if [ -e "$inspect" ]; then
            [ -d "$inspect" ] && [ "$(stat -c %u -- "$inspect")" = 0 ] ||
                fail "Directory must be owned by root: $inspect"
            perm=$(stat -c %a -- "$inspect")
            if [ "$((0$perm & 022))" -ne 0 ] &&
                { [ "$inspect" = "$1" ] || [ "$((0$perm & 01000))" -eq 0 ]; }; then
                fail "Unsafe permissions on $inspect"
            fi
        fi
        inspect=$(dirname -- "$inspect")
    done
}
protected() {
    [ ! -L "$1" ] && [ "$(stat -c '%u:%a:%F' -- "$1")" = "$2" ] ||
        fail 'Saved bootstrap ownership, permissions or type are invalid'
}
ref_ok() { valid "$1" '^[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'; }
file_digest() { sha256sum -- "$1" | cut -d ' ' -f 1; }
docker() { command docker --host unix:///var/run/docker.sock "$@"; }
docker_ready() { docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; }

install_docker() {
    docker_ready && return
    [ "$ask" = yes ] || [ "$apt" = yes ] || fail 'Approve Docker installation with --install-docker'
    printf '%s\n' 'Installing Docker Engine and Compose…'
    export DEBIAN_FRONTEND=noninteractive
    apt-get -qq update
    apt-get -qq install -y ca-certificates curl gpg >/dev/null
    curl --disable --proto '=https' --fail --silent --show-error --max-time 30 \
        --max-filesize 65536 --output "$work/docker.asc" "https://download.docker.com/linux/$distro/gpg"
    mkdir -m 700 "$work/gnupg"
    fingerprints=$(gpg --batch --homedir "$work/gnupg" --with-colons --show-keys "$work/docker.asc" |
        awk -F: '$1=="pub"{primary=1; keys++} primary && $1=="fpr"{print $10; primary=0}
                 END {if (keys != 1) print "invalid"}')
    [ "$fingerprints" = 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ] ||
        fail 'The Docker APT signing key did not match its pinned fingerprint'
    install -d -m 755 /etc/apt/keyrings
    install -m 644 "$work/docker.asc" /etc/apt/keyrings/dvt-docker.asc
    printf '%s\n' "deb [arch=amd64 signed-by=/etc/apt/keyrings/dvt-docker.asc] https://download.docker.com/linux/$distro $codename stable" \
        | install -m 644 /dev/stdin /etc/apt/sources.list.d/dvt-docker.list
    apt-get -qq update
    apt-get -qq install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null
    docker_ready || fail 'Docker Engine or Compose remains unavailable'
}

storage_paths() {
    docker_root=$(docker info --format '{{.DockerRootDir}}')
    path_check "$docker_root"
    [ -d "$docker_root" ] || fail 'Docker backing directory is missing'
    case "$dir/" in "$docker_root/"*) fail 'Keep DVT data outside Docker storage' ;; esac
    case "$docker_root/" in "$dir/"*) fail 'Keep Docker storage outside DVT data' ;; esac
    drivers=$(docker info --format '{{range .DriverStatus}}{{index . 0}}={{index . 1}}{{println}}{{end}}')
    if printf '%s\n' "$drivers" | grep -Fxq 'driver-type=io.containerd.snapshotter.v1'; then
        if [ -z "$containerd" ]; then
            docker_pid=$(systemctl show --property=MainPID --value docker.service)
            containerd_pid=$(systemctl show --property=MainPID --value containerd.service)
            [ -r "/proc/$docker_pid/cmdline" ] && [ -r "/proc/$containerd_pid/cmdline" ] &&
                tr '\000' '\n' <"/proc/$docker_pid/cmdline" | grep -Fxq -- '--containerd=/run/containerd/containerd.sock' ||
                fail 'Use --containerd-root for this Docker image store'
            [ "$(tr '\000' '\n' <"/proc/$containerd_pid/cmdline")" = /usr/bin/containerd ] ||
                fail 'Use --containerd-root for this Docker image store'
            /usr/bin/containerd config dump >"$work/containerd.conf" 2>"$work/containerd.err" ||
                { cat "$work/containerd.err" >&2; fail 'Cannot read containerd configuration'; }
            containerd=$(awk -F '[ \t]*=[ \t]*' '$1=="root" {gsub(/[\047"]/, "", $2); print $2}' "$work/containerd.conf")
        fi
        path_check "$containerd"
        [ -d "$containerd" ] || fail 'Containerd backing directory is missing'
        case "$dir/" in "$containerd/"*) fail 'Keep DVT data outside containerd storage' ;; esac
        case "$containerd/" in "$dir/"*) fail 'Keep containerd storage outside DVT data' ;; esac
    else
        [ -z "$containerd" ] || fail 'This Docker Engine does not use the containerd image store'
    fi
}

install_unit() {
    unit=/etc/systemd/system/dvt-bootstrap-$project.service
    unit_tmp=$(mktemp /etc/systemd/system/.dvt-bootstrap-XXXXXX)
    cat >"$unit_tmp" <<UNIT
[Unit]
Description=DVT resume for $project
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/sh $control/host-launch.sh resume $dir

[Install]
WantedBy=multi-user.target
UNIT
    if [ -e "$unit" ] || [ -L "$unit" ]; then
        [ ! -L "$unit" ] && cmp -s "$unit_tmp" "$unit" ||
            { rm -f -- "$unit_tmp"; fail 'A different resume unit owns this Compose project'; }
        rm -f -- "$unit_tmp"
    else
        chmod 644 "$unit_tmp"
        mv -T -- "$unit_tmp" "$unit"
    fi
    systemctl daemon-reload
    systemctl --quiet enable "dvt-bootstrap-$project.service"
}

run_bootstrap() {
    # Host mode is narrow: Docker socket plus the protected instance, its config,
    # host distribution identity and read-only backing directories. No host root bind.
    call=$1
    base=$2
    shift 2
    if [ -n "$containerd" ] && [ "$call" = bootstrap ]; then
        set -- "$@" --containerd-root "$containerd"
    fi
    if [ "$ask" != yes ] || [ "$call" != bootstrap ]; then
        set -- "$@" --non-interactive
    fi
    set -- "$manager" "$base/host_bootstrap.py" "$call" --contained --dir "$dir" "$@"
    if [ -n "$containerd" ]; then
        set -- --mount "type=bind,src=$containerd,dst=$containerd,readonly" "$@"
    fi
    if [ "$base" = /run/dvt-launch ]; then
        set -- --mount "type=bind,src=$work,dst=$base,readonly" "$@"
    fi
    terminal=/dev/null
    if [ "$ask" = yes ] && [ "$call" = bootstrap ]; then
        set -- -i -t "$@"
        terminal=/dev/tty
    fi
    docker run --rm --pull=never --platform linux/amd64 --network host --entrypoint python3 \
        --mount "type=bind,src=$dir,dst=$dir" \
        --mount "type=bind,src=$docker_root,dst=$docker_root,readonly" \
        --mount 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock' \
        --mount 'type=bind,src=/etc/os-release,dst=/run/dvt-host-os,readonly' \
        "$@" <"$terminal"
}

[ "$(id -u)" = 0 ] && [ -d /run/systemd/system ] || fail 'Use sudo on the systemd host'
[ "$#" -ge 2 ] || fail 'Use ACTION and the canonical data directory'
mode=$1 dir=$2 control=$2/.bootstrap
shift 2
case "$mode" in
    new|dispatch|repeat|resume|maintenance|maintenance-extend|maintenance-defer|cancel-preparation|recover-manager|return-to-source|restore-start) ;;
    *) fail 'Unknown managed action' ;;
esac
path_check "$dir"
check_saved_selection() {
    protected "$control/launch-host.conf" '0:600:regular file'
    saved_pin=$(sed -n '6p' "$control/launch-host.conf")
    saved_version=${saved_pin%% *}
    [ -n "$saved_version" ] || fail 'Existing installation has no saved selection. Omit release options to resume.'
    case "$saved_version" in *-rc*) saved_channel=rc ;; *) saved_channel=stable ;; esac
    [ "$1" = "$saved_channel" ] && { [ -z "$2" ] || [ "$2" = "$saved_version" ]; } ||
        fail 'Existing installation has a different release selection. Use the wizard to change versions.'
}
if [ "$mode" = dispatch ]; then
    if [ ! -e "$control" ] && [ ! -L "$control" ]; then
        exit 73
    fi
    protected "$control" '0:700:directory'
    protected "$control/host-launch.sh" '0:700:regular file'
    if [ -n "${8:-}" ]; then check_saved_selection "$8" "${9:-}"; fi
    exec /bin/sh "$control/host-launch.sh" repeat "$dir" "$1" "$2" "$3" "$4" "$5" "$6" "$7"
fi

if [ "$mode" = new ]; then
    shim=$1 manager=$2 digest=$3 size=$4 catalog=$5 catalog_hash=$6 catalog_ca=$7
    shift 7
    ref_ok "$manager" || fail 'Invalid pinned manager'
    work=$(mktemp -d /tmp/dvt-launch.XXXXXX)
    trap 'rm -rf -- "$work"' 0
    trap 'exit 1' HUP INT TERM
    head -c 1048577 >"$work/host_bootstrap.py"
    [ "$(wc -c <"$work/host_bootstrap.py")" -eq "$size" ] &&
        [ "sha256:$(file_digest "$work/host_bootstrap.py")" = "$digest" ] ||
        fail 'Approved bootstrap changed before root execution'
    printf '%s' "$catalog" >"$work/catalog.json"
    [ "sha256:$(file_digest "$work/catalog.json")" = "$catalog_hash" ] ||
        fail 'Catalog policy changed before root execution'
    printf '%s' "$shim" >"$work/host-launch.sh"
    if [ -n "$catalog_ca" ]; then
        printf '%s\n' "$catalog_ca" >"$work/catalog-ca.pem"
    fi
fi

path_check /run/dvt-bootstrap
install -d -m 700 /run/dvt-bootstrap
exec 9>/run/dvt-bootstrap/bootstrap.lock
flock -x 9

if [ "$mode" = new ] && [ ! -e "$control" ] && [ ! -L "$control" ]; then
    project=${1:-dvt} port=${2:-8888} public_url=$3 containerd=$4 ask=$5 apt=$6 pair=$7 distro=$8 codename=$9
    valid "$project" '^[a-z0-9][a-z0-9_-]{0,63}$' || fail 'Invalid Compose project'
    valid "$port" '^[0-9]{1,5}$' && [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] ||
        fail 'Invalid HTTPS port (1024–65535)'
    unit=/etc/systemd/system/dvt-bootstrap-$project.service
    [ ! -e "$unit" ] && [ ! -L "$unit" ] || fail 'A resume unit already reserves this project'
    if [ -d "$dir" ] && [ -n "$(find "$dir" -mindepth 1 -maxdepth 1 \
        ! \( -name '.bootstrap-partial-*' -type d \) -print -quit)" ]; then
        fail 'The selected data directory is not empty'
    fi
    if [ -n "$public_url" ]; then
        valid "$public_url" '^https?://([a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(:[0-9]{1,5})?/?$' ||
            fail 'Enter the separate public HTTP(S) origin of DVT'
    fi
    install_docker
    storage_paths
    printf '%s\n' 'Downloading the installation manager…'
    docker pull --quiet --platform linux/amd64 "$manager" >/dev/null
    install -d -m 700 -- "$dir"
    printf '%s\n' "$project" "$manager" "$docker_root" "$containerd" "$port" >"$work/launch-host.conf"
    if [ -n "${10:-}" ]; then
        printf '%s %s\n' "${11}" "${12}" >>"$work/launch-host.conf"
    fi
    set -- --managed --project "$project" --port "$port" --manager "$manager" \
        --public-url "${public_url:-http://localhost}" \
        --release-catalog-config /run/dvt-launch/catalog.json
    if [ -n "$catalog_ca" ]; then
        set -- "$@" --release-catalog-ca /run/dvt-launch/catalog-ca.pem
    fi
    if [ "$pair" = yes ]; then set -- "$@" --new-pairing-token; fi
    run_bootstrap bootstrap /run/dvt-launch "$@"
    install_unit
    exit
fi

protected "$control" '0:700:directory'
protected "$control/host-launch.sh" '0:700:regular file'
protected "$control/host_bootstrap.py" '0:600:regular file'
protected "$control/launch-bootstrap.sha256" '0:600:regular file'
protected "$control/launch-host.conf" '0:600:regular file'
expected=$(cat -- "$control/launch-bootstrap.sha256")
valid "$expected" '^[0-9a-f]{64}$' &&
    [ "$(file_digest "$control/host_bootstrap.py")" = "$expected" ] ||
    fail 'The saved managed bootstrap failed its digest check'
{
    IFS= read -r project && IFS= read -r manager && IFS= read -r docker_root &&
        IFS= read -r containerd && IFS= read -r port || fail 'Invalid saved instance metadata'
    if IFS= read -r pin; then
        valid "$pin" '^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)? sha256:[0-9a-f]{64}$' || fail 'Invalid saved release pin'
        if IFS= read -r extra; then fail 'Invalid saved instance metadata'; fi
    fi
} <"$control/launch-host.conf"
valid "$project" '^[a-z0-9][a-z0-9_-]{0,63}$' && ref_ok "$manager" ||
    fail 'Invalid saved project or manager pin'
path_check "$docker_root"
if [ -n "$containerd" ]; then path_check "$containerd"; fi
docker_ready || fail 'Docker or Compose is unavailable for the existing instance'
if [ "$mode" = repeat ] || [ "$mode" = new ]; then
    [ -z "$1" ] || [ "$1" = "$project" ] || fail 'A different project is already stored'
    [ -z "$2" ] || [ "$2" = "$port" ] || fail 'A different HTTPS port is already stored'
    [ -z "$4" ] || [ "$4" = "$containerd" ] || fail 'A different containerd root is already stored'
    if [ "$mode" = new ] && [ -n "${10:-}" ]; then check_saved_selection "${10}" "${11}"; fi
    ask=$5
    pair=$7
    if [ -n "$3" ]; then set -- --managed --public-url "$3"; else set -- --managed; fi
    if [ "$pair" = yes ]; then set -- "$@" --new-pairing-token; fi
    run_bootstrap bootstrap "$control" "$@"
    install_unit
else
    if [ "$mode" = resume ]; then
        [ "$#" -eq 0 ] || fail 'resume takes only the data directory'
    else
        [ "$#" -eq 2 ] && [ "$1" = --operation-id ] &&
            valid "$2" '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' ||
            fail 'Select the active operation with --operation-id UUID'
    fi
    ask=no
    run_bootstrap "$mode" "$control" "$@"
fi
ROOT_SH
)

as_root() {
    if [ "$(id -u)" = 0 ]; then "$@"; else /usr/bin/sudo -- "$@"; fi
}

codename=$(os_value VERSION_CODENAME)
case "$distro:$codename" in
    debian:trixie|ubuntu:noble) ;;
    *) fail 'The installer requires an official supported distribution codename' ;;
esac
selection_channel=
if [ "$explicit_selection" = yes ]; then selection_channel=$channel; fi
if [ -e "$dir" ]; then
    result=0
    as_root /bin/sh -c "$runtime" dvt-runtime dispatch "$dir" \
        "$project" "$port" "$resume_url" "$containerd" "$ask" "$apt" "$pair" "$selection_channel" "$requested_version" || result=$?
    [ "$result" -eq 73 ] || exit "$result"
fi

valid "$origin" "$origin_pattern" || fail 'Select a valid HTTPS catalog'
if [ "$origin" = "$public_origin" ] && { [ "$private_rc" = yes ] || [ -n "$ca_file" ]; }; then
    fail '--test-rc and extra CA require an explicitly selected private catalog'
fi
umask 077
tmp=$(mktemp -d /tmp/dvt-install.XXXXXX)
trap 'rm -rf -- "$tmp"' 0
trap 'exit 1' HUP INT TERM

fetch() {
    if [ -n "$ca_file" ]; then set -- --cacert "$ca_file" "$@"; fi
    curl --disable --proto '=https' --max-time 30 --fail --silent --show-error "$@"
}
set -- --data-urlencode "channel=$channel"
if [ -n "$requested_version" ]; then set -- "$@" --data-urlencode "version=$requested_version"; fi
status=$(fetch --max-filesize 65536 --output "$tmp/catalog.json" --dump-header "$tmp/headers" \
    --write-out '%{http_code}' --header 'Accept: application/vnd.dvt.install+json' \
    --get --data-urlencode "distribution=$distro" --data-urlencode "distribution_version=$version" \
    --data-urlencode 'platform=linux/amd64' "$@" \
    "$origin/api/v1/dvt/releases/install") || {
    if [ "$status" = 404 ]; then
        fail "No approved initial release for $distro $version ($channel${requested_version:+, $requested_version})"
    fi
    fail 'HTTPS catalog/certificate is unavailable'
}
[ "$status" = 200 ] || fail 'The HTTPS catalog did not return an approved initial release'

header() {
    value=$(awk -v field="$1" '
        { sub(/\r$/, ""); sep=index($0, ":") }
        sep && tolower(substr($0, 1, sep-1)) == field {
            hits++; value=substr($0, sep+1); sub(/^[ \t]+/, "", value)
        }
        END { if (hits != 1 || !length(value)) exit 1; print value }
    ' "$tmp/headers") || fail "Invalid installation descriptor ($1)"
    printf '%s\n' "$value"
}
format=$(header x-dvt-launch-format)
selected=$(header x-dvt-release-version)
selected_channel=$(header x-dvt-release-channel)
manifest=$(header x-dvt-manifest-digest)
catalog_origin=$(header x-dvt-catalog-origin)
catalog_hash=$(header x-dvt-catalog-digest)
asset_origin=$(header x-dvt-bootstrap-origin)
asset_url=$(header x-dvt-bootstrap-url)
asset_size=$(header x-dvt-bootstrap-size)
asset_digest=$(header x-dvt-bootstrap-digest)
manager=$(header x-dvt-manager-image)
version_pattern='^[0-9]{1,16}\.[0-9]{1,16}\.[0-9]{1,16}'
if [ "$channel" = rc ]; then version_pattern=$version_pattern'-rc[0-9]{1,16}'; fi
[ "$format" = 1 ] && [ "$selected_channel" = "$channel" ] && [ "$catalog_origin" = "$origin" ] &&
    valid "$selected" "$version_pattern"'$' && valid "$manifest" "$digest_pattern" &&
    valid "$catalog_hash" "$digest_pattern" && valid "$asset_digest" "$digest_pattern" &&
    valid "$asset_origin" "$origin_pattern" && valid "$asset_size" '^[1-9][0-9]{0,6}$' &&
    [ "$asset_size" -le 1048576 ] && valid "$manager" "$manager_pattern" ||
    fail 'Invalid installation descriptor'
[ -z "$requested_version" ] || [ "$selected" = "$requested_version" ] ||
    fail "Catalog returned $selected instead of requested version $requested_version"
case "$asset_url" in "$asset_origin/"?*) ;; *) fail 'Invalid HTTPS bootstrap origin' ;; esac
valid "$asset_url" '^https://[a-z0-9.:-]+/[a-zA-Z0-9._~/%-]+$' ||
    fail 'Invalid HTTPS bootstrap URL'
[ -s "$tmp/catalog.json" ] && [ "sha256:$(sha256sum "$tmp/catalog.json" | cut -d ' ' -f 1)" = "$catalog_hash" ] ||
    fail 'Invalid catalog policy digest'
status=$(fetch --max-filesize "$asset_size" --output "$tmp/host_bootstrap.py" --write-out '%{http_code}' "$asset_url") ||
    fail 'Approved bootstrap unavailable or has the wrong size'
[ "$status" = 200 ] && [ "$(wc -c <"$tmp/host_bootstrap.py")" -eq "$asset_size" ] &&
    [ "sha256:$(sha256sum "$tmp/host_bootstrap.py" | cut -d ' ' -f 1)" = "$asset_digest" ] ||
    fail 'The approved bootstrap failed its signed size or digest check'
catalog=$(cat -- "$tmp/catalog.json")
catalog_ca=
if [ -n "$ca_file" ]; then
    [ "$(wc -c <"$ca_file")" -le 32768 ] || fail 'The private catalog CA is too large'
    catalog_ca=$(cat -- "$ca_file")
fi
as_root /bin/sh -c "$runtime" dvt-runtime new "$dir" \
    "$runtime" "$manager" "$asset_digest" "$asset_size" "$catalog" "$catalog_hash" "$catalog_ca" \
    "$project" "$port" "$public_url" "$containerd" "$ask" "$apt" "$pair" "$distro" "$codename" \
    "$selection_channel" "$selected" "$manifest" <"$tmp/host_bootstrap.py"

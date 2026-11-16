#!/bin/bash
set -euo pipefail
work=$1
if ! [[ "$work" =~ ^/tmp/dvt-staging-test\.[A-Za-z0-9]{8}$ ]]; then exit 64; fi
suffix=$(basename "$work" | cut -d. -f2 | tr '[:upper:]' '[:lower:]')
tag="dvt-stage02-mtu-$suffix:local"
net="dvt-stage02-mtu-$suffix"
server="dvt-stage02-https-$suffix"
if docker image inspect "$tag" >/dev/null 2>&1 || docker network inspect "$net" >/dev/null 2>&1 || docker container inspect "$server" >/dev/null 2>&1; then exit 65; fi
cleanup() {
    docker container rm -f "$server" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
    docker image rm "$tag" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker build --quiet --tag "$tag" "$work"
mkdir -m 700 "$work/tls"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -keyout "$work/tls/tls.key" -out "$work/tls/tls.crt" -subj /CN=fixture-tls -addext subjectAltName=DNS:fixture-tls 2>/dev/null
docker network create --internal --driver bridge --opt com.docker.network.driver.mtu=1280 "$net" >/dev/null
docker run -d --rm --name "$server" --network "$net" --network-alias fixture-tls --read-only \
    --mount "type=bind,source=$work/tls,target=/tls,readonly" "$tag" \
    /opt/testing/bin/python /case/mtu_probe.py server >/dev/null
for retry in 1 2 3 4 5; do
    if docker exec "$server" /opt/testing/bin/python -c 'import socket; socket.create_connection(("127.0.0.1", 9443), 1).close()'; then break; fi
    sleep 1
done
docker run --rm --network "$net" --read-only \
    --mount "type=bind,source=$work/tls/tls.crt,target=/public-ca.crt,readonly" "$tag" \
    /opt/testing/bin/python /case/mtu_probe.py client

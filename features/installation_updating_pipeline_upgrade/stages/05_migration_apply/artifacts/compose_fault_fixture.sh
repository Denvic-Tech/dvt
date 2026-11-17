#!/usr/bin/env bash
# Isolated Compose fixture: synthetic application containers, real PostgreSQL.
set -euo pipefail

work="$(mktemp -d)"
name="dvt-s05-$(basename "$work" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
project="$name-off"
profile=()

compose() {
    docker compose --project-directory "$work" -p "$project" -f "$work/compose.yaml" "${profile[@]}" "$@"
}

cleanup() {
    for suffix in off on; do
        project="$name-$suffix"
        profile=(--profile ai-mcp)
        compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    done
    rm -f "$work/compose.yaml"
    rmdir "$work"
}
trap cleanup EXIT

cat >"$work/compose.yaml" <<'YAML'
x-role: &role
  image: postgres:15.3-alpine
  entrypoint: [sh, -ec]
  command: [ "exec sleep 3600" ]
  healthcheck:
    test: [CMD, "true"]
    interval: 1s
    timeout: 1s
    retries: 2

services:
  postgres:
    image: postgres:15.3-alpine
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: stage-05-fixture-only
      POSTGRES_DB: test
    volumes: [ "pgtmp:/var/lib/postgresql/data" ]
    healthcheck:
      test: [CMD, "pg_isready", "-h", "127.0.0.1", "-U", "test", "-d", "test"]
      interval: 1s
      timeout: 1s
      retries: 25

  installation_manager:
    <<: *role

  migrate:
    image: postgres:15.3-alpine
    entrypoint: [sh, -ec]
    environment:
      PGPASSWORD: stage-05-fixture-only
    command:
      - |
        sql() { psql -h postgres -U test -d test -XAtq -v ON_ERROR_STOP=1 -c "$$1"; }
        [ "$$(sql 'SELECT fail FROM fixture_settings')" = f ] || exit 43
        sql 'UPDATE fixture_settings SET starts = starts + 1' >/dev/null
        sql "WITH receipt AS (
          INSERT INTO fixture_receipts VALUES (1) ON CONFLICT DO NOTHING RETURNING id
        ) UPDATE fixture_settings SET applied = applied + 1 WHERE EXISTS (SELECT id FROM receipt)" >/dev/null
    restart: "no"
    depends_on:
      postgres: {condition: service_healthy}

  gateway:
    <<: *role
    command:
      - |
        sleep 7
        touch /tmp/ready
        exec sleep 3600
    healthcheck:
      test: [CMD, "test", "-f", "/tmp/ready"]
      interval: 1s
      timeout: 1s
      retries: 2
    depends_on:
      migrate: {condition: service_completed_successfully}

  orchestrator:
    <<: *role
    depends_on:
      migrate: {condition: service_completed_successfully}

  project-scheduler:
    <<: *role
    depends_on:
      migrate: {condition: service_completed_successfully}

  task-worker:
    <<: *role
    depends_on:
      migrate: {condition: service_completed_successfully}

  proxy:
    <<: *role
    depends_on:
      gateway: {condition: service_healthy}

  dvt-ai-mcp:
    <<: *role
    profiles: [ai-mcp]
    depends_on:
      gateway: {condition: service_healthy}

volumes:
  pgtmp: {}
YAML

sql() {
    compose exec -T postgres psql -U test -d test -XAtq -v ON_ERROR_STOP=1 -c "$1"
}

running() {
    compose ps --services --status running | grep -Fxq "$1"
}

wait_for() {
    local n
    for n in {1..35}; do
        if "$@"; then return 0; fi
        sleep 1
    done
    return 1
}

healthy() {
    local container
    container="$(compose ps -q "$1")"
    [ -n "$container" ] &&
        [ "$(docker inspect -f '{{.State.Health.Status}}' "$container")" = healthy ]
}

docker image inspect postgres:15.3-alpine >/dev/null 2>&1 || docker pull postgres:15.3-alpine
for suffix in off on; do
    project="$name-$suffix"
    profile=()
    if [ "$suffix" = on ]; then profile=(--profile ai-mcp); fi
    compose up -d postgres installation_manager
    wait_for healthy postgres
    sql 'CREATE TABLE fixture_settings (fail bool, starts integer, applied integer);
         INSERT INTO fixture_settings VALUES (true, 0, 0);
         CREATE TABLE fixture_receipts (id integer PRIMARY KEY);'

    if compose up -d --pull never; then echo "Fault did not stop Compose" >&2; exit 1; fi
    for role in gateway orchestrator project-scheduler task-worker proxy dvt-ai-mcp; do
        if running "$role"; then echo "Unmigrated role started: $role" >&2; exit 1; fi
    done
    wait_for healthy installation_manager
    [ "$(sql 'SELECT applied FROM fixture_settings')" = 0 ]

    sql 'UPDATE fixture_settings SET fail = false;'
    if compose up -d --pull never; then echo "Gateway delay did not exercise failure" >&2; exit 1; fi
    [ "$(sql 'SELECT applied FROM fixture_settings')" = 1 ]
    if running proxy; then echo "Proxy started before Gateway readiness" >&2; exit 1; fi
    wait_for healthy gateway
    compose up -d --pull never

    for role in gateway orchestrator project-scheduler task-worker proxy installation_manager; do
        wait_for healthy "$role"
    done
    if [ "$suffix" = on ]; then
        wait_for healthy dvt-ai-mcp
    elif running dvt-ai-mcp; then
        echo "Disabled MCP started" >&2
        exit 1
    fi
    [ "$(sql 'SELECT applied FROM fixture_settings')" = 1 ]
    echo "PASS: profile=$suffix; failed migration held back apps; late Gateway recovered; core applications=1; migration starts=$(sql 'SELECT starts FROM fixture_settings')"
done

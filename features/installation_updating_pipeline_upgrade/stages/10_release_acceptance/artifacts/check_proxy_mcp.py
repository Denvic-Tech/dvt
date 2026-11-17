"""Probe the actual Proxy Caddyfile with an already loaded Caddy image."""

# ruff: noqa: T201 - the probe prints HTTP results for the acceptance report

import argparse
import subprocess
from pathlib import Path

SOURCE = "services/proxy/Caddyfile"
ROOT = Path(__file__).resolve().parents[5]
UPSTREAMS = b"""
:18081 {
    respond "ui {http.request.uri}" 200
}
:18082 {
    respond "mcp {http.request.method} {http.request.uri}" 202
}
:18083 {
    respond "gateway {http.request.uri}" 200
}
"""
PROBE = r"""
cat > /tmp/dvt-proxy.Caddyfile
caddy version
caddy run --adapter caddyfile --config /tmp/dvt-proxy.Caddyfile > /tmp/dvt-proxy.log 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do
    if wget -q -O /dev/null http://127.0.0.1/workspace; then
        break
    fi
    if ! kill -0 "$pid" 2>/dev/null || [ "$attempt" -eq 30 ]; then
        cat /tmp/dvt-proxy.log >&2
        exit 1
    fi
    sleep .1
done

probe() {
    method="$1"
    uri="$2"
    shift 2
    : > /tmp/dvt-body
    wget -S -O /tmp/dvt-body "$@" "http://127.0.0.1$uri" 2>/tmp/dvt-headers || true
    status="$(awk '/HTTP\// { print $2; exit }' /tmp/dvt-headers)"
    printf '%s\t%s\t%s\t%s\n' "$method" "$uri" "$status" "$(cat /tmp/dvt-body)"
}
probe GET /mcp
probe POST /mcp/configured --post-data '{}'
probe GET /mcp-example
probe GET /workspace
probe GET /api/health
"""


def check(image: str, source: bytes, profile: str | None) -> bool:
    variables = [
        "-e", "UI_HOST=127.0.0.1", "-e", "UI_PORT=18081",
        "-e", "AI_MCP_HOST=127.0.0.1", "-e", "AI_MCP_PORT=18082",
        "-e", "GATEWAY_HOST=127.0.0.1", "-e", "GATEWAY_PORT=18083",
    ]
    if profile is not None:
        variables.extend(("-e", f"DVT_AI_MCP_ENABLED={profile}"))
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--pull=never", "--network", "none", "--interactive",
            *variables, "--entrypoint", "sh", image, "-ec", PROBE,
        ],
        input=source + UPSTREAMS,
        capture_output=True,
        check=True,
        timeout=30,
    )
    version, *rows = result.stdout.decode().splitlines()
    print(f"{profile or 'default'} Caddy {version}")
    enabled = profile == "true"
    expected = {
        ("GET", "/mcp"): ("202", "mcp GET /mcp") if enabled else ("404", ""),
        ("POST", "/mcp/configured"): (
            ("202", "mcp POST /mcp/configured") if enabled else ("404", "")
        ),
        ("GET", "/mcp-example"): ("200", "ui /mcp-example"),
        ("GET", "/workspace"): ("200", "ui /workspace"),
        ("GET", "/api/health"): ("200", "gateway /api/health"),
    }
    actual = {}
    for row in rows:
        method, uri, status, body = row.split("\t")
        actual[(method, uri)] = status, body
        print(f"{profile or 'default'} {method} {uri} -> {status} {body}".rstrip())
    return actual == expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Local Caddy or Proxy image")
    parser.add_argument("--source-revision", help="Read the original Caddyfile from this Git commit")
    args = parser.parse_args()
    source = (
        subprocess.check_output(["git", "show", f"{args.source_revision}:{SOURCE}"], cwd=ROOT)
        if args.source_revision else (ROOT / SOURCE).read_bytes()
    )
    try:
        results = [check(args.image, source, profile) for profile in (None, "false", "true")]
    except subprocess.CalledProcessError as error:
        print(error.stderr.decode(errors="replace"))
        return 1
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

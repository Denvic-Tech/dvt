import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent
os.chdir(PROJECT_DIR)

env = os.environ.copy()
env.update({
    "DOCKER_BUILDKIT": "1",
})

TRUE_TOKENS = {"1", "true", "yes", "on"}
FALSE_TOKENS = {"0", "false", "no", "off", ""}


def configure_ai_mcp_profile() -> None:
    raw = env.get("DVT_AI_MCP_ENABLED", "false").strip().lower()
    if raw in TRUE_TOKENS:
        enabled = True
    elif raw in FALSE_TOKENS:
        enabled = False
    else:
        raise ValueError(f"Invalid DVT_AI_MCP_ENABLED value: {raw!r}")
    if enabled and len(env.get("DVT_AI_MCP_INTERNAL_SECRET", "")) < 32:
        raise ValueError(
            "DVT_AI_MCP_INTERNAL_SECRET must contain at least 32 characters "
            "when DVT_AI_MCP_ENABLED=true"
        )
    env["DVT_AI_MCP_ENABLED"] = "true" if enabled else "false"
    profiles = [item.strip() for item in env.get("COMPOSE_PROFILES", "").split(",")]
    profiles = [item for item in profiles if item and item != "ai-mcp"]
    if enabled:
        profiles.append("ai-mcp")
    env["COMPOSE_PROFILES"] = ",".join(profiles)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--remove-orphans",
        action="store_true",
        help="Pass --remove-orphans to docker compose up.",
    )
    return parser.parse_args()


def ensure_docker_network(name: str) -> None:
    result = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        check=True,
    )

    networks = result.stdout.splitlines()

    if name not in networks:
        print(f"Creating docker network: {name}")
        subprocess.run(["docker", "network", "create", name], check=True)
    else:
        print(f"Docker network '{name}' already exists")


if __name__ == "__main__":
    args = parse_args()
    configure_ai_mcp_profile()
    ensure_docker_network("dvt-net")

    compose_command = [
        "docker",
        "compose",
        "--project-directory",
        PROJECT_DIR,
        "-f",
        "docker/docker-compose.base.yaml",
        "-f",
        "docker/docker-compose.dev.yaml",
    ]
    if env["DVT_AI_MCP_ENABLED"] == "false":
        subprocess.run(
            [*compose_command, "--profile", "ai-mcp", "stop", "dvt-ai-mcp"],
            env=env,
            check=False,
        )
        subprocess.run(
            [*compose_command, "--profile", "ai-mcp", "rm", "-f", "dvt-ai-mcp"],
            env=env,
            check=False,
        )

    command = [
        *compose_command,
        "up",
        "-d",
        "--no-deps",
    ]
    if args.remove_orphans:
        command.append("--remove-orphans")
    command.extend(["--scale", f"task-worker={os.getenv('DVT_TASK_WORKERS_COUNT', '1')}"])

    result = subprocess.run(command, env=env, check=False)
    sys.exit(result.returncode)

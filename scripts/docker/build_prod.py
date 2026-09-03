import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
os.chdir(PROJECT_DIR)

env = os.environ.copy()
env.update(
    {
        "DOCKER_BUILDKIT": "1",
    }
)


if __name__ == "__main__":
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(PROJECT_DIR),
            "-f",
            "docker/docker-compose.base.yaml",
            "-f",
            "docker/docker-compose.dev.yaml",
            "-f",
            "docker/docker-compose.prod.override.yaml",
            "--profile",
            "ai-mcp",
            "build",
        ],
        env=env,
        check=False,
    )
    sys.exit(result.returncode)

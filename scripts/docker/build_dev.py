import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent.parent
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
            PROJECT_DIR,
            "-f",
            "docker/docker-compose.base.yaml",
            "-f",
            "docker/docker-compose.dev.yaml",
            "--profile",
            "ai-mcp",
            "build",
        ],
        env=env,
        check=False,
    )
    sys.exit(result.returncode)

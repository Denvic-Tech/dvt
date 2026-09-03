import os
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import PROJECT_DIR, build_prod_compose_command, run_command
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_prod_compose_command,
        run_command,
    )

os.chdir(PROJECT_DIR)

env = os.environ.copy()
docker_config_dir = Path(PROJECT_DIR) / "tmp" / "docker-config"
docker_config_dir.mkdir(parents=True, exist_ok=True)
env.update(
    {
        "DOCKER_BUILDKIT": "1",
        "DOCKER_CONFIG": str(docker_config_dir),
    }
)


if __name__ == "__main__":
    exit_code = run_command(
        build_prod_compose_command(
            PROJECT_DIR,
            "build",
            "orchestrator",
            "task-worker",
            "project-scheduler",
            "gateway",
        ),
        env=env,
    )
    sys.exit(exit_code)

import argparse
import os
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_testing_compose_command,
        resolve_test_target,
        run_command,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_testing_compose_command,
        resolve_test_target,
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
    parser = argparse.ArgumentParser(description="Run dockerized DVT unit tests.")
    parser.add_argument(
        "test_path",
        nargs="?",
        default=None,
        help="Optional test file/directory path (or pytest node id with ::) inside tests/unit.",
    )
    args, pytest_args = parser.parse_known_args()

    try:
        test_target = resolve_test_target(
            project_dir=PROJECT_DIR,
            tests_dir="tests/unit",
            test_path=args.test_path,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    build_exit_code = run_command(
        build_testing_compose_command(PROJECT_DIR, "build", "tester_unit"),
        env=env,
    )
    if build_exit_code != 0:
        sys.exit(build_exit_code)

    test_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_unit",
            "python",
            "-m",
            "pytest",
            test_target,
            *pytest_args,
        ),
        env=env,
    )
    sys.exit(test_exit_code)

import atexit
import os
import shutil
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        parse_test_script_args,
        resolve_test_target,
        run_command,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        parse_test_script_args,
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
    test_path, pytest_args, extension_name = parse_test_script_args()

    if test_path is not None:
        try:
            test_selection = [
                "--core-target",
                resolve_test_target(
                    project_dir=PROJECT_DIR,
                    tests_dir="tests/unit",
                    test_path=test_path,
                ),
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    elif extension_name is not None:
        test_selection = ["--extension", extension_name]
    else:
        test_selection = ["--core-with-extensions"]

    extensions_dir = create_isolated_extensions_dir(
        project_dir=PROJECT_DIR,
        tests_type="unit",
    )
    atexit.register(shutil.rmtree, extensions_dir, ignore_errors=True)
    env["EXTENSIONS_VOLUME_PATH"] = str(extensions_dir)

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
            "scripts/docker/run_tests_with_extensions.py",
            "--tests-type",
            "unit",
            "--extensions-dir",
            "/app/extensions",
            *test_selection,
            "--",
            *pytest_args,
        ),
        env=env,
    )
    sys.exit(test_exit_code)

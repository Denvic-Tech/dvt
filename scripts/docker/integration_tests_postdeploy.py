import os
import shlex
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_testing_compose_command,
        collect_extension_test_dirs,
        ensure_external_docker_network,
        parse_test_script_args,
        resolve_extension_test_target,
        resolve_test_target,
        run_command,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_testing_compose_command,
        collect_extension_test_dirs,
        ensure_external_docker_network,
        parse_test_script_args,
        resolve_extension_test_target,
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
            test_targets = [
                resolve_test_target(
                    project_dir=PROJECT_DIR,
                    tests_dir="tests/integration",
                    test_path=test_path,
                )
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    elif extension_name is not None:
        try:
            test_targets = [
                resolve_extension_test_target(
                    project_dir=PROJECT_DIR,
                    extension_name=extension_name,
                    tests_type="integration",
                )
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    else:
        test_targets = ["tests/integration"]
        extension_dirs = collect_extension_test_dirs(
            project_dir=PROJECT_DIR,
            tests_type="integration",
        )
        if extension_dirs:
            print(f"Найдены тесты расширений: {', '.join(extension_dirs)}")
        test_targets.extend(extension_dirs)

    tester_build_exit_code = run_command(
        build_testing_compose_command(PROJECT_DIR, "build", "tester_integration"),
        env=env,
    )
    if tester_build_exit_code != 0:
        sys.exit(tester_build_exit_code)

    ensure_external_docker_network("dvt-net", env=env)

    pytest_args_str = shlex.join(pytest_args)
    test_targets_str = shlex.join(test_targets)
    test_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_integration",
            "bash",
            "-c",
            (
                "python scripts/docker/install_extensions_locally.py --target-dir /app/extensions"
                f" && pytest -s -vv {test_targets_str} {pytest_args_str}"
            ),
        ),
        env=env,
    )
    sys.exit(test_exit_code)

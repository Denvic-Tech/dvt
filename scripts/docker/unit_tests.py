import os
import shlex
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_testing_compose_command,
        collect_extension_test_dirs,
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
        # Конкретный тест — разрешаем как обычно
        try:
            test_targets = [
                resolve_test_target(
                    project_dir=PROJECT_DIR,
                    tests_dir="tests/unit",
                    test_path=test_path,
                )
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    elif extension_name is not None:
        # Конкретное расширение
        try:
            test_targets = [
                resolve_extension_test_target(
                    project_dir=PROJECT_DIR,
                    extension_name=extension_name,
                    tests_type="unit",
                )
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    else:
        # Все тесты: основной проект + все расширения
        test_targets = ["tests/unit"]
        extension_dirs = collect_extension_test_dirs(
            project_dir=PROJECT_DIR,
            tests_type="unit",
        )
        if extension_dirs:
            print(f"Найдены тесты расширений: {', '.join(extension_dirs)}")
        test_targets.extend(extension_dirs)

    build_exit_code = run_command(
        build_testing_compose_command(PROJECT_DIR, "build", "tester_unit"),
        env=env,
    )
    if build_exit_code != 0:
        sys.exit(build_exit_code)

    pytest_args_str = shlex.join(pytest_args)
    test_targets_str = shlex.join(test_targets)
    test_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_unit",
            "bash",
            "-c",
            (
                "python scripts/docker/install_extensions_locally.py --target-dir /app/extensions"
                f" && pytest {test_targets_str} {pytest_args_str}"
            ),
        ),
        env=env,
    )
    sys.exit(test_exit_code)

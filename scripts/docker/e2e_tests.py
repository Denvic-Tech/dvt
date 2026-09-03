import os
import shlex
import sys

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_app_compose_command,
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
        build_app_compose_command,
        build_testing_compose_command,
        collect_extension_test_dirs,
        parse_test_script_args,
        resolve_extension_test_target,
        resolve_test_target,
        run_command,
    )

os.chdir(PROJECT_DIR)

env = os.environ.copy()
env.update(
    {
        "DOCKER_BUILDKIT": "1",
    }
)


if __name__ == "__main__":
    test_path, pytest_args, extension_name = parse_test_script_args()

    if test_path is not None:
        try:
            test_targets = [
                resolve_test_target(
                    project_dir=PROJECT_DIR,
                    tests_dir="tests/e2e",
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
                    tests_type="e2e",
                )
            ]
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(2)
    else:
        test_targets = ["tests/e2e"]
        extension_dirs = collect_extension_test_dirs(
            project_dir=PROJECT_DIR,
            tests_type="e2e",
        )
        if extension_dirs:
            print(f"Найдены тесты расширений: {', '.join(extension_dirs)}")
        test_targets.extend(extension_dirs)

    app_build_exit_code = run_command(
        build_app_compose_command(
            PROJECT_DIR,
            "build",
            "orchestrator",
            "task-worker",
            "project-scheduler",
            "gateway",
        ),
        env=env,
    )
    if app_build_exit_code != 0:
        sys.exit(app_build_exit_code)

    tester_build_exit_code = run_command(
        build_testing_compose_command(PROJECT_DIR, "build", "tester_e2e"),
        env=env,
    )
    if tester_build_exit_code != 0:
        sys.exit(tester_build_exit_code)

    pytest_args_str = shlex.join(pytest_args)
    test_targets_str = shlex.join(test_targets)
    e2e_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_e2e",
            "bash",
            "-c",
            (
                "python scripts/docker/install_extensions_locally.py --target-dir /app/extensions"
                " && pytest -s -vv --log-cli-level=DEBUG"
                " --log-cli-format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'"
                f" {test_targets_str} {pytest_args_str}"
            ),
        ),
        env=env,
    )
    sys.exit(e2e_exit_code)

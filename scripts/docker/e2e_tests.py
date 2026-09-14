import atexit
import os
import shutil
import sys

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_app_compose_command,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        parse_test_script_args,
        resolve_test_target,
        run_command,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_app_compose_command,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        parse_test_script_args,
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
            test_selection = [
                "--core-target",
                resolve_test_target(
                    project_dir=PROJECT_DIR,
                    tests_dir="tests/e2e",
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
        tests_type="e2e",
    )
    atexit.register(shutil.rmtree, extensions_dir, ignore_errors=True)
    env["EXTENSIONS_VOLUME_PATH"] = str(extensions_dir)

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

    e2e_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_e2e",
            "python",
            "scripts/docker/run_tests_with_extensions.py",
            "--tests-type",
            "e2e",
            "--extensions-dir",
            "/app/extensions",
            *test_selection,
            "--",
            "-s",
            "-vv",
            "--log-cli-level=DEBUG",
            "--log-cli-format=%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            *pytest_args,
        ),
        env=env,
    )
    sys.exit(e2e_exit_code)

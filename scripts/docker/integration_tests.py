import atexit
import os
import shutil
import sys
from pathlib import Path

try:
    from scripts.docker.test_runner import (
        PROJECT_DIR,
        build_prod_compose_command,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        ensure_external_docker_network,
        parse_test_script_args,
        resolve_test_target,
        run_command,
    )
except ModuleNotFoundError:
    from test_runner import (  # type: ignore[no-redef]
        PROJECT_DIR,
        build_prod_compose_command,
        build_testing_compose_command,
        create_isolated_extensions_dir,
        ensure_external_docker_network,
        parse_test_script_args,
        resolve_test_target,
        run_command,
    )

os.chdir(PROJECT_DIR)

_RELEASE_TEST_SERVICES = (
    "orchestrator",
    "task-worker",
    "project-scheduler",
    "gateway",
)


def resolve_docker_config_dir(environment: dict[str, str]) -> Path:
    configured_dir = environment.get("DOCKER_CONFIG", "").strip()
    if configured_dir:
        return Path(configured_dir)
    return Path(PROJECT_DIR) / "tmp" / "docker-config"


env = os.environ.copy()
docker_config_dir = resolve_docker_config_dir(env)
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
                    tests_dir="tests/integration",
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

    use_candidates = env.get("DVT_INTEGRATION_USE_CANDIDATES", "false").lower() == "true"
    require_candidate_digests = (
        env.get("DVT_INTEGRATION_REQUIRE_DIGESTS", "false").lower() == "true"
    )
    if use_candidates:
        image_prefix = env.get("DVT_INTEGRATION_IMAGE_PREFIX", "").strip().rstrip("/")
        image_tag = env.get("DVT_INTEGRATION_IMAGE_TAG", "").strip()
        if not image_prefix or not image_tag:
            print(
                "DVT_INTEGRATION_USE_CANDIDATES=true requires "
                "DVT_INTEGRATION_IMAGE_PREFIX and DVT_INTEGRATION_IMAGE_TAG.",
                file=sys.stderr,
            )
            sys.exit(2)

        for service_name in _RELEASE_TEST_SERVICES:
            candidate_ref = f"{image_prefix}/{service_name}:{image_tag}"
            source_ref = candidate_ref
            if require_candidate_digests:
                digest_key = f"DVT_CANDIDATE_DIGEST_{service_name.upper().replace('-', '_')}"
                candidate_digest = env.get(digest_key, "").strip()
                if not candidate_digest.startswith("sha256:"):
                    print(
                        f"{digest_key} must contain a sha256 digest when "
                        "DVT_INTEGRATION_REQUIRE_DIGESTS=true.",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                source_ref = f"{image_prefix}/{service_name}@{candidate_digest}"

            pull_exit_code = run_command(["docker", "pull", source_ref], env=env)
            if pull_exit_code != 0:
                sys.exit(pull_exit_code)

            if source_ref != candidate_ref:
                tag_exit_code = run_command(
                    ["docker", "image", "tag", source_ref, candidate_ref],
                    env=env,
                )
                if tag_exit_code != 0:
                    sys.exit(tag_exit_code)
    else:
        app_build_exit_code = run_command(
            build_prod_compose_command(
                PROJECT_DIR,
                "build",
                *_RELEASE_TEST_SERVICES,
            ),
            env=env,
        )
        if app_build_exit_code != 0:
            sys.exit(app_build_exit_code)

    extensions_dir = create_isolated_extensions_dir(
        project_dir=PROJECT_DIR,
        tests_type="integration",
    )
    atexit.register(shutil.rmtree, extensions_dir, ignore_errors=True)
    env["EXTENSIONS_VOLUME_PATH"] = str(extensions_dir)

    tester_build_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "build",
            "tester_integration",
        ),
        env=env,
    )
    if tester_build_exit_code != 0:
        sys.exit(tester_build_exit_code)

    ensure_external_docker_network("dvt-net", env=env)

    test_exit_code = run_command(
        build_testing_compose_command(
            PROJECT_DIR,
            "run",
            "--rm",
            "tester_integration",
            "python",
            "scripts/docker/run_tests_with_extensions.py",
            "--tests-type",
            "integration",
            "--extensions-dir",
            "/app/extensions",
            *test_selection,
            "--",
            "-s",
            "-vv",
            *pytest_args,
        ),
        env=env,
    )
    sys.exit(test_exit_code)

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTH_ENV_MAPPING = {
    "JWT_ACCESS_TOKEN_SECRET_KEY": "DVT_JWT_ACCESS_TOKEN_SECRET_KEY",
    "JWT_REFRESH_TOKEN_SECRET_KEY": "DVT_JWT_REFRESH_TOKEN_SECRET_KEY",
    "JWT_ONETIME_TOKEN_SECRET_KEY": "DVT_JWT_ONETIME_TOKEN_SECRET_KEY",
    "JWT_API_TOKEN_SECRET_KEY": "DVT_JWT_API_TOKEN_SECRET_KEY",
    "CODE_HASH_SALT": "DVT_CODE_HASH_SALT",
}


def _gateway_environment(path: str) -> dict[str, str]:
    content = yaml.safe_load((PROJECT_ROOT / path).read_text(encoding="utf-8"))
    return content["services"]["gateway"]["environment"]


def test_published_compose_requires_unique_gateway_auth_secrets() -> None:
    environment = _gateway_environment("docker-compose.yaml")

    assert environment["ENVIRONMENT"] == "prod"
    for process_name, deployment_name in AUTH_ENV_MAPPING.items():
        assert environment[process_name].startswith(f"${{{deployment_name}:?")


def test_dev_and_prod_override_forward_gateway_auth_secrets() -> None:
    dev_environment = _gateway_environment("docker/docker-compose.dev.yaml")
    prod_environment = _gateway_environment("docker/docker-compose.prod.override.yaml")

    for process_name, deployment_name in AUTH_ENV_MAPPING.items():
        expected = f"${{{deployment_name}:-}}"
        assert dev_environment[process_name] == expected
        assert prod_environment[process_name] == expected

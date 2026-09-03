from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest


DEFAULT_TEST_FERNET_KEY = "Y8RFpaIxSaAFNsB352tpLXl5znUw5anEKIZgclOezak="
DEFAULT_SUPERADMIN_EMAIL = "INTEGRATION-superadmin@example.com"
DEFAULT_SUPERADMIN_PASSWORD = "INTEGRATIONSuperadmin#12345"
DEFAULT_ORGANIZATION_NAME = "INTEGRATION organization"
DEFAULT_LICENSE_KEY = "INTEGRATION-license"
DEFAULT_GATEWAY_ORIGINS = "http://localhost:5173"
DEFAULT_IMAGE_PREFIX = os.getenv("DVT_INTEGRATION_IMAGE_PREFIX", "dvt")
DEFAULT_IMAGE_TAG = os.getenv("DVT_INTEGRATION_IMAGE_TAG", "latest")


@dataclass(frozen=True)
class IntegrationTestSettings:
    repo_root: Path
    tmp_dir: Path
    lmdb_path: Path
    fernet_key: str = DEFAULT_TEST_FERNET_KEY
    default_email: str = DEFAULT_SUPERADMIN_EMAIL
    default_password: str = DEFAULT_SUPERADMIN_PASSWORD
    default_organization_name: str = DEFAULT_ORGANIZATION_NAME
    default_license_key: str = DEFAULT_LICENSE_KEY
    gateway_origins: str = DEFAULT_GATEWAY_ORIGINS
    dvt_image_prefix: str = DEFAULT_IMAGE_PREFIX
    dvt_image_tag: str = DEFAULT_IMAGE_TAG

    def dvt_image(self, service_name: str) -> str:
        return f"{self.dvt_image_prefix}/{service_name}:{self.dvt_image_tag}"


def build_integration_test_settings() -> IntegrationTestSettings:
    repo_root = Path(__file__).resolve().parents[3]
    tmp_dir = repo_root / "tmp" / "pytest" / "integration_runtime"
    lmdb_path = tmp_dir / "usrak_lmdb_data"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    lmdb_path.mkdir(parents=True, exist_ok=True)
    return IntegrationTestSettings(
        repo_root=repo_root,
        tmp_dir=tmp_dir,
        lmdb_path=lmdb_path,
    )


def apply_integration_test_env(settings: IntegrationTestSettings | None = None) -> IntegrationTestSettings:
    resolved_settings = settings or build_integration_test_settings()
    os.environ.setdefault("LOG_TO_DB", "false")
    os.environ.setdefault("LMDB_PATH", str(resolved_settings.lmdb_path))
    return resolved_settings


@pytest.fixture(scope="session")
def integration_test_settings() -> IntegrationTestSettings:
    settings = build_integration_test_settings()
    apply_integration_test_env(settings)
    return settings

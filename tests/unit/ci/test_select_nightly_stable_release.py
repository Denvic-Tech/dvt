from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "scripts" / ".ci" / "select_nightly_stable_release.py"
SPEC = spec_from_file_location("select_nightly_stable_release", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_resolve_stable_tag_uses_latest_stable_release() -> None:
    tags = [
        {"name": "1.22.0rc1"},
        {"name": "1.21.1"},
        {"name": "1.21.0"},
    ]

    assert MODULE.resolve_stable_tag("latest-stable", tags) == "1.21.1"


def test_resolve_stable_tag_accepts_explicit_stable_release() -> None:
    assert MODULE.resolve_stable_tag("1.20.3") == "1.20.3"


@pytest.mark.parametrize(
    "requested_version",
    [
        "1.20.3rc1",
        "1.20.3-rc1",
        "v1.20.3",
        "latest",
        "dev",
    ],
)
def test_resolve_stable_tag_rejects_non_stable_release(requested_version: str) -> None:
    with pytest.raises(RuntimeError, match="stable X.Y.Z"):
        MODULE.resolve_stable_tag(requested_version)

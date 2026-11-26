"""The published 1.24.0 Linux release carried by the legacy conversion image."""

from datetime import datetime
from pathlib import Path

from ..domain.operation_state import ReleasePin
from ..domain.release_manifest import ReleaseManifest, strict_json
from ..infrastructure.release_verification import TrustPolicy, verify_file

PACKAGE = Path(__file__).resolve().parents[1] / "legacy_bridge"
BASELINE = ReleasePin(
    "dvt-1.24.0-ci-16007",
    "sha256:7488fcdc6af891960bd27e9b47844d6242558e642c8c5ba82e56814635f3aadc",
)


def load_baseline(trust: TrustPolicy) -> tuple[ReleasePin, ReleaseManifest, bytes]:
    """Verify the historical kit authorized by this exact bridge image."""
    content = (PACKAGE / "manifest.json").read_bytes()
    # Legacy installations can arrive after the catalog entry expires. This single
    # historical digest still requires a trusted root and a non-revoked signer.
    issued = datetime.fromisoformat(strict_json(content)["payload"]["issued_at"])
    release = trust.verify(content, BASELINE, now=issued)
    compose = (PACKAGE / "compose.yaml").read_bytes()
    verify_file(compose, release.platforms["linux/amd64"].compose, "legacy baseline Compose")
    return BASELINE, release, compose

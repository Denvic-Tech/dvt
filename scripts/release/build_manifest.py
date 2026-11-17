"""Create the signed v1 release manifest and content-addressed client assets."""

import argparse
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.version import Version

from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import (
    ImageDescriptor,
    ReleaseManifest,
    SignedRelease,
    canonical_json,
    digest_of,
    strict_json,
)
from services.installation_manager.infrastructure.release_verification import (
    MANIFEST_CONTEXT,
    TrustPolicy,
)
from services.installation_manager.infrastructure.staging_compose import validate_template

PLATFORM = "linux/amd64"
BOOTSTRAP = "services/installation_manager/host_bootstrap.py"
COMPOSE = "docker-compose.yaml"


def normalized_version(version: str) -> str:
    return version.replace("rc", "-rc") if "-" not in version else version


def git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(source), *args])


def source_repository(image: str) -> str:
    """Resolve a Compose image's default tag and qualify short Docker Hub names."""
    repository = image.split(":${", 1)[0] if ":${" in image else image.rsplit(":", 1)[0]
    first = repository.split("/", 1)[0]
    if "/" not in repository:
        return f"docker.io/library/{repository}"
    if "." not in first and ":" not in first:
        return f"docker.io/{repository}"
    return repository


def load_compose(content: bytes) -> dict:
    validate_template(content)
    return yaml.safe_load(content)


def pinned_compose(source: bytes, images: dict[str, dict], *, isolated: bool) -> bytes:
    compose = load_compose(source)
    if compose["services"].keys() != images.keys():
        raise ValueError("The inventory must include every Compose service and profile")
    for role, service in compose["services"].items():
        image = ImageDescriptor.model_validate(images[role])
        if not isolated and image.reference.rsplit("@", 1)[0] != source_repository(service["image"]):
            raise ValueError(f"The image repository differs from the tagged Compose for {role}")
        service["image"] = image.reference
    return yaml.safe_dump(compose, sort_keys=False, allow_unicode=True).encode("utf-8")


def write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"Conflicting content already exists at {path.name}")
        return
    with path.open("xb") as stream:
        stream.write(content)


def https_origin(origin: str) -> str:
    url = urlsplit(origin)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or any(char.isspace() or char in "\\?#" for char in origin)
    ):
        raise ValueError("Use an HTTPS asset origin without a path or credentials")
    return f"https://{url.netloc}"


def asset_descriptor(origin: str, filename: str, content: bytes) -> tuple[dict, Path]:
    digest = digest_of(content)
    relative = Path("dvt") / "release-assets" / digest.removeprefix("sha256:") / filename
    return {"url": f"{origin}/{relative.as_posix()}", "digest": digest, "size": len(content)}, relative


def build(args: argparse.Namespace) -> str:
    if args.backend_sha or args.ui_sha:
        if not args.isolated or not args.backend_sha or not args.ui_sha:
            raise ValueError("Explicit archive SHAs require both SHAs and --isolated")
        backend_sha, ui_sha = args.backend_sha, args.ui_sha
        compose, bootstrap = ((args.source / name).read_bytes() for name in (COMPOSE, BOOTSTRAP))
    else:
        backend_sha = git(args.source, "rev-parse", "HEAD").decode().strip()
        mode, kind, ui_sha = (
            git(args.source, "ls-tree", backend_sha, "services/ui").decode().split("\t")[0].split()
        )
        if (mode, kind) != ("160000", "commit"):
            raise ValueError("The source must contain a pinned UI gitlink")
        if not args.isolated:
            project = tomllib.loads(git(args.source, "show", f"{backend_sha}:pyproject.toml").decode())
            if normalized_version(project["project"]["version"]) != args.version:
                raise ValueError("The release version differs from the source")
            if git(args.source / "services/ui", "rev-parse", "HEAD").decode().strip() != ui_sha:
                raise ValueError("The UI checkout differs from the pinned gitlink")
        compose, bootstrap = (
            git(args.source, "show", f"{backend_sha}:{name}") for name in (COMPOSE, BOOTSTRAP)
        )

    origin = https_origin(args.asset_origin)
    images = strict_json(args.images.read_bytes())
    policy = strict_json(args.policy.read_bytes())
    if set(policy) != {"environment", "schema", "compatibility", "expires_at"}:
        raise ValueError("The reviewed release policy has missing or extra fields")
    if not args.isolated:
        config = Config(str(args.source / "alembic.ini"))
        config.set_main_option("script_location", str(args.source.resolve() / "migrations"))
        heads = ScriptDirectory.from_config(config).get_heads()
        if heads != [policy["schema"]["target_revision"]]:
            raise ValueError("The signed target schema differs from the built migration head")
        if any(
            normalized_version(policy["compatibility"][role]) != args.version
            for role in ("manager_version", "executor_version")
        ):
            raise ValueError("Manager and executor versions must describe this source")
    compose = pinned_compose(compose, images, isolated=args.isolated)
    compose_info, compose_path = asset_descriptor(origin, "compose.yaml", compose)
    bootstrap_info, bootstrap_path = asset_descriptor(origin, "bootstrap.py", bootstrap)
    payload = {
        "format_version": 1,
        "release_id": args.release_id,
        "version": args.version,
        "channel": "rc" if "-rc" in args.version else "stable",
        "backend_sha": backend_sha,
        "ui_sha": ui_sha,
        "issued_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        **policy,
        "platforms": {PLATFORM: {"compose": compose_info, "bootstrap": bootstrap_info, "images": images}},
    }
    manifest = ReleaseManifest.model_validate(payload)
    compatibility = manifest.compatibility
    if manifest.database_schema.initial_install and (
        Version(compatibility.minimum_preparer_version) > Version(compatibility.executor_version)
    ):
        raise ValueError("The initial release requires a newer preparer than its packaged executor")
    signer = strict_json(args.signer.read_bytes())
    if set(signer) != {"signing_key", "key_signature", "private_key"}:
        raise ValueError("The signing credentials have an unexpected format")
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signer["private_key"]))
    envelope = {
        "payload": payload,
        "signing_key": signer["signing_key"],
        "key_signature": signer["key_signature"],
        "manifest_signature": private_key.sign(MANIFEST_CONTEXT + canonical_json(payload)).hex(),
    }
    SignedRelease.model_validate(envelope)
    content = canonical_json(envelope)
    digest = digest_of(content)
    trust = TrustPolicy.from_document(strict_json(args.trust.read_bytes()))
    trust.verify(content, ReleasePin(release_id=args.release_id, manifest_digest=digest))
    write_once(args.output_dir / compose_path, compose)
    write_once(args.output_dir / bootstrap_path, bootstrap)
    write_once(args.output_dir / "manifest.json", content)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--asset-origin", required=True)
    for name in ("images", "policy", "signer", "trust", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path())
    parser.add_argument("--isolated", action="store_true", help="Allow test mirror and version fixtures")
    parser.add_argument("--backend-sha")
    parser.add_argument("--ui-sha")
    args = parser.parse_args()
    if normalized_version(args.version) != args.version:
        parser.error("Use the canonical version, for example 1.24.0-rc2")
    try:
        digest = build(args)
    except subprocess.CalledProcessError:
        print("Could not establish the pinned release source", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, RecursionError):
        # Input validation can include entire objects, including signing credentials.
        print("Could not assemble or verify the signed release inputs", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

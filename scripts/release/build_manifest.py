"""Create the signed v1 release manifest and content-addressed client assets."""

import argparse
import ast
import io
import subprocess
import sys
import tarfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from alembic.script.revision import Revision, RevisionError, RevisionMap
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from packaging.version import Version

from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import (
    ImageDescriptor,
    ReleaseManifest,
    SignedRelease,
    SigningKey,
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
    parsed = Version(version)
    if (
        len(parsed.release) != 3 or parsed.epoch or parsed.local or parsed.dev is not None
        or parsed.post is not None or (parsed.pre is not None and parsed.pre[0] != "rc")
    ):
        raise ValueError("Use a three-part stable or RC release version")
    return parsed.base_version + (f"-rc{parsed.pre[1]}" if parsed.pre else "")


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


def migration_head(files: list[bytes]) -> str:
    revisions = []
    names_seen = set()
    for content in files:
        metadata = {}
        for node in ast.parse(content).body:
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            for name in set(names) & {"revision", "down_revision", "depends_on", "branch_labels"}:
                if name in metadata:
                    raise ValueError("Migration metadata must have one literal assignment")
                metadata[name] = ast.literal_eval(node.value)
        if not {"revision", "down_revision"} <= metadata.keys():
            raise ValueError("Migration revision and parent must be declared literally")
        name = metadata["revision"]
        if not isinstance(name, str) or not name or name in names_seen:
            raise ValueError("Migration revisions must be unique nonempty strings")
        names_seen.add(name)
        revisions.append(Revision(
            name, metadata["down_revision"],
            dependencies=metadata.get("depends_on"), branch_labels=metadata.get("branch_labels"),
        ))
    try:
        heads = RevisionMap(lambda: iter(revisions)).heads
    except (RevisionError, KeyError) as error:
        raise ValueError("The migration graph is invalid") from error
    if len(heads) != 1:
        raise ValueError("The exact release source must contain one Alembic head")
    return heads[0]


def source_head(source: Path, revision: str | None) -> str:
    # Read literal metadata only, so migrations cannot import backend services.
    if revision is None:
        files = [path.read_bytes() for path in sorted((source / "migrations/versions").glob("*.py"))
                 if path.name != "__init__.py"]
    else:
        archive = git(source, "archive", revision, "migrations/versions")
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            files = [stream.extractfile(member).read() for member in stream.getmembers()
                     if member.isfile() and member.name.count("/") == 2
                     and member.name.endswith(".py") and not member.name.endswith("/__init__.py")]
    return migration_head(files)


def project_policy(project: dict, version: str, head: str, issued: datetime, cert: SigningKey) -> dict:
    settings = project["tool"]["dvt"]["release"]
    expected = {
        "manifest_ttl_days", "minimum_preparer_version", "journal_format", "initial_install",
        "from_releases", "required_extensions", "environment",
    }
    if set(settings) != expected:
        raise ValueError("The source release settings have missing or extra fields")
    days = settings["manifest_ttl_days"]
    if type(days) is not int or days < 1:
        raise ValueError("The release manifest TTL must be a positive integer")
    minimum = normalized_version(settings["minimum_preparer_version"])
    until = datetime.fromisoformat(cert.valid_until)
    # Compare first so an arbitrarily large configured integer cannot overflow timedelta.
    expires = until if days > (until - issued).days else issued + timedelta(days=days)
    return {
        "environment": settings["environment"],
        "schema": {
            "target_revision": head,
            "initial_install": settings["initial_install"],
            "from_releases": settings["from_releases"],
            "required_extensions": settings["required_extensions"],
        },
        "compatibility": {
            "manager_version": version, "executor_version": version,
            "minimum_preparer_version": minimum, "journal_format": settings["journal_format"],
        },
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
    }


def build(args: argparse.Namespace) -> str:
    policy_path = getattr(args, "policy", None)
    project = None
    revision = None
    if args.backend_sha or args.ui_sha:
        if not args.isolated or not args.backend_sha or not args.ui_sha:
            raise ValueError("Explicit archive SHAs require both SHAs and --isolated")
        backend_sha, ui_sha = args.backend_sha, args.ui_sha
        compose, bootstrap = ((args.source / name).read_bytes() for name in (COMPOSE, BOOTSTRAP))
        if policy_path is None or args.version is None:
            project = tomllib.loads((args.source / "pyproject.toml").read_text(encoding="utf-8"))
    else:
        backend_sha = git(args.source, "rev-parse", "HEAD").decode().strip()
        revision = backend_sha
        mode, kind, ui_sha = (
            git(args.source, "ls-tree", backend_sha, "services/ui").decode().split("\t")[0].split()
        )
        if (mode, kind) != ("160000", "commit"):
            raise ValueError("The source must contain a pinned UI gitlink")
        project = tomllib.loads(
            git(args.source, "show", f"{backend_sha}:pyproject.toml").decode("utf-8")
        )
        if (
            not args.isolated
            and git(args.source / "services/ui", "rev-parse", "HEAD").decode().strip() != ui_sha
        ):
            raise ValueError("The UI checkout differs from the pinned gitlink")
        compose, bootstrap = (
            git(args.source, "show", f"{backend_sha}:{name}") for name in (COMPOSE, BOOTSTRAP)
        )

    version = normalized_version(args.version or project["project"]["version"])
    if not args.isolated and version != normalized_version(project["project"]["version"]):
        raise ValueError("The release version differs from the exact source")
    origin = https_origin(args.asset_origin)
    images = strict_json(args.images.read_bytes())
    issued = datetime.now(UTC).replace(microsecond=0)
    signer = strict_json(args.signer.read_bytes())
    if set(signer) != {"signing_key", "key_signature", "private_key"}:
        raise ValueError("The signing credentials have an unexpected format")
    cert = SigningKey.model_validate(signer["signing_key"])
    if not datetime.fromisoformat(cert.valid_from) <= issued < datetime.fromisoformat(cert.valid_until):
        raise ValueError("The signing certificate is not currently valid")
    head = source_head(args.source, revision) if not args.isolated or policy_path is None else None
    if policy_path is None:
        policy = project_policy(project, version, head, issued, cert)
    else:
        policy = strict_json(policy_path.read_bytes())
        if set(policy) != {"environment", "schema", "compatibility", "expires_at"}:
            raise ValueError("The reviewed release policy has missing or extra fields")
        if not args.isolated:
            if head != policy["schema"]["target_revision"]:
                raise ValueError("The signed target schema differs from the built migration head")
            if any(
                normalized_version(policy["compatibility"][role]) != version
                for role in ("manager_version", "executor_version")
            ):
                raise ValueError("Manager and executor versions must describe this source")
    compose = pinned_compose(compose, images, isolated=args.isolated)
    compose_info, compose_path = asset_descriptor(origin, "compose.yaml", compose)
    bootstrap_info, bootstrap_path = asset_descriptor(origin, "bootstrap.py", bootstrap)
    payload = {
        "format_version": 1,
        "release_id": args.release_id,
        "version": version,
        "channel": "rc" if "-rc" in version else "stable",
        "backend_sha": backend_sha,
        "ui_sha": ui_sha,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        **policy,
        "platforms": {PLATFORM: {"compose": compose_info, "bootstrap": bootstrap_info, "images": images}},
    }
    manifest = ReleaseManifest.model_validate(payload)
    compatibility = manifest.compatibility
    if manifest.database_schema.initial_install and (
        Version(compatibility.minimum_preparer_version) > Version(compatibility.executor_version)
    ):
        raise ValueError("The initial release requires a newer preparer than its packaged executor")
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
    parser.add_argument("--version", help="Expected source version or Git tag")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--asset-origin", required=True)
    parser.add_argument("--policy", type=Path, help="Legacy explicit policy for standalone callers")
    for name in ("images", "signer", "trust", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path())
    parser.add_argument("--isolated", action="store_true", help="Allow test mirror and version fixtures")
    parser.add_argument("--backend-sha")
    parser.add_argument("--ui-sha")
    args = parser.parse_args()
    try:
        digest = build(args)
    except subprocess.CalledProcessError:
        print("Could not establish the pinned release source", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, RecursionError, SyntaxError, tarfile.TarError):
        # Input validation can include entire objects, including signing credentials.
        print("Could not assemble or verify the signed release inputs", file=sys.stderr)
        return 1
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

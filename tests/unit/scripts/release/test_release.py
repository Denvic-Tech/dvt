import io
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.release import acceptance, build_manifest, image_inventory
from scripts.release.build_manifest import (
    BOOTSTRAP,
    COMPOSE,
    build,
    pinned_compose,
    source_repository,
)

from services.installation_manager.domain.release_manifest import (
    canonical_json,
    digest_of,
    strict_json,
)
from services.installation_manager.host_bootstrap import bootstrap_images
from services.installation_manager.infrastructure.release_verification import (
    KEY_CONTEXT,
    MANIFEST_CONTEXT,
)

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/data/installation_manager/verified_staging/manifest.json"


@pytest.fixture
def package(tmp_path):
    release = strict_json(FIXTURE.read_bytes())["payload"]
    source = (ROOT / COMPOSE).read_bytes()
    services = yaml.safe_load(source)["services"]
    inventory = {
        role: {
            "reference": source_repository(settings["image"]) + "@sha256:" + "1" * 64,
            "compressed_bytes": 1, "unpacked_bytes": 1, "unpacked_inodes": 1,
        }
        for role, settings in services.items()
    }
    issued_year = datetime.now(UTC).year
    root = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    certificate = {
        "root_id": "unit", "key_id": "unit-online",
        "public_key": signer.public_key().public_bytes_raw().hex(),
        "valid_from": f"{issued_year - 1}-01-01T00:00:00Z",
        "valid_until": f"{issued_year + 2}-01-01T00:00:00Z",
    }
    values = {
        "images": inventory,
        "policy": {
            **{key: release[key] for key in ("environment", "schema", "compatibility")},
            "expires_at": f"{issued_year + 1}-01-01T00:00:00Z",
        },
        "signer": {
            "signing_key": certificate,
            "key_signature": root.sign(KEY_CONTEXT + canonical_json(certificate)).hex(),
            "private_key": signer.private_bytes_raw().hex(),
        },
        "trust": {"roots": {"unit": root.public_key().public_bytes_raw().hex()}, "revoked_signers": []},
    }
    inputs = {}
    for key, value in values.items():
        inputs[key] = tmp_path / f"{key}.json"
        inputs[key].write_bytes(canonical_json(value))
    args = SimpleNamespace(
        **inputs, output_dir=tmp_path / "release", version="1.24.0", backend_sha="a" * 40,
        ui_sha="b" * 40, isolated=True, source=ROOT, release_id="test-release",
        asset_origin="https://assets.example.test",
    )
    build(args)
    return args, inventory


def test_release_signs_exact_full_compose_and_bootstrap(package):
    args, inventory = package
    content = (args.output_dir / "manifest.json").read_bytes()
    manifest = acceptance.verified_manifest(content, args.trust)
    platform = manifest.platforms["linux/amd64"]
    assert (manifest.backend_sha, manifest.ui_sha) == (args.backend_sha, args.ui_sha)
    for asset in (platform.compose, platform.bootstrap):
        path = args.output_dir / asset.url.split(args.asset_origin + "/")[1]
        assert (path.stat().st_size, digest_of(path.read_bytes())) == (asset.size, asset.digest)
    rendered = yaml.safe_load(
        (args.output_dir / platform.compose.url.split(args.asset_origin + "/")[1]).read_bytes()
    )
    assert {role: service["image"] for role, service in rendered["services"].items()} == {
        role: item["reference"] for role, item in inventory.items()
    }
    bootstrap = args.output_dir / platform.bootstrap.url.split(args.asset_origin + "/")[1]
    assert bootstrap.read_bytes() == (ROOT / BOOTSTRAP).read_bytes()


@pytest.mark.parametrize("problem", ["missing_profile", "different_repository"])
def test_production_packager_rejects_invalid_image_set(package, problem):
    _, inventory = package
    if problem == "missing_profile":
        del inventory["dvt-ai-mcp"]
    else:
        inventory["valkey"]["reference"] = inventory["valkey"]["reference"].replace(
            "docker.io", "mirror.example.test"
        )
    with pytest.raises(ValueError):
        pinned_compose((ROOT / COMPOSE).read_bytes(), inventory, isolated=False)


def test_acceptance_requires_all_exact_vm_results_and_evidence(package, tmp_path):
    args, inventory = package
    content = (args.output_dir / "manifest.json").read_bytes()
    manifest = acceptance.verified_manifest(content, args.trust)
    matrix = acceptance.matrix_template(content, manifest, "123", "https://candidate.example.test")
    with pytest.raises(ValueError):
        acceptance.issue_receipt(content, manifest, matrix, tmp_path, "123")
    note = tmp_path / "synthetic.txt"
    note.write_bytes(b"Unit test evidence.")
    for index, run in enumerate(matrix["runs"]):
        run["vm"] = f"sample-{index}"
        run["docker_version"] = run["compose_version"] = "100.0.0"
        run["images"] = {role: item["reference"] for role, item in inventory.items()}
        for case_id, case in run["cases"].items():
            if index and case_id != "AT-01":
                continue
            case["checks"] = dict.fromkeys(case["checks"], "PASS")
            case["metrics"] = dict.fromkeys(acceptance.METRICS.get(case_id, set()), 1)
            case["evidence"] = {"synthetic.txt": digest_of(note.read_bytes())}
            if case_id == "AT-09":
                case["restore_target"] = {
                    "vm": "restore-clean", "distribution": "ubuntu",
                    "distribution_version": "24.04", "platform": "linux/amd64",
                    "compose_version": "100.0.0", "docker_version": "100.0.0",
                }
    result = acceptance.issue_receipt(content, manifest, matrix, tmp_path, "123")
    assert result == {
        "format_version": 1, "result": "passed", "version": manifest.version,
        "run_id": "gitlab-pipeline-123", "manifest_digest": digest_of(content),
    }
    missing = deepcopy(matrix)
    missing["runs"].pop()
    with pytest.raises(ValueError, match="missing for a declared VM profile"):
        acceptance.issue_receipt(content, manifest, missing, tmp_path, "123")
    missing = deepcopy(matrix)
    missing["runs"][0]["cases"]["AT-12"] = acceptance.pending_case("AT-12")
    with pytest.raises(ValueError, match="missing required AT cases"):
        acceptance.issue_receipt(content, manifest, missing, tmp_path, "123")
    wrong_restore = deepcopy(matrix)
    run = wrong_restore["runs"][0]
    run["cases"]["AT-09"]["restore_target"]["vm"] = run["vm"]
    with pytest.raises(ValueError, match="separate clean supported VM"):
        acceptance.issue_receipt(content, manifest, wrong_restore, tmp_path, "123")
    with pytest.raises(ValueError, match="exact envelope"):
        acceptance.issue_receipt(content + b" ", manifest, matrix, tmp_path, "123")
    note.write_bytes(b"Tampered evidence")
    with pytest.raises(ValueError, match="Evidence digest mismatch"):
        acceptance.issue_receipt(content, manifest, matrix, tmp_path, "123")


def test_catalog_bootstrap_can_use_one_approved_manager_digest():
    manager = "registry.example.test/dvt/installation_manager@sha256:" + "1" * 64
    args = SimpleNamespace(manager=manager, candidate=None, executor=None)
    assert bootstrap_images(args, catalog={"origin": "https://catalog.example.test"}) == (
        manager, manager, manager,
    )
    assert bootstrap_images(args, catalog=None) == (manager, None, None)
    args.candidate = manager
    with pytest.raises(ValueError, match="distinct"):
        bootstrap_images(args, catalog=None)


def test_inventory_selects_leaf_from_an_immutable_registry_index(monkeypatch):
    repository = "registry.example.test/dvt/gateway"
    leaf = "sha256:" + "1" * 64
    index = canonical_json({
        "manifests": [
            {"platform": {"os": "unknown", "architecture": "unknown"}, "digest": "attestation"},
            {"platform": {"os": "linux", "architecture": "amd64"}, "digest": leaf},
        ]
    })
    monkeypatch.setattr("scripts.release.image_inventory.skopeo", lambda *_: index)
    assert (
        image_inventory.leaf_reference(f"{repository}@{digest_of(index)}", "auth")
        == f"{repository}@{leaf}"
    )
    with pytest.raises(ValueError, match="BuildKit digest"):
        image_inventory.leaf_reference(f"{repository}@{leaf}", "auth")



def test_initial_install_rejects_rc_executor_below_stable_preparer_minimum(package):
    args, _ = package
    policy = strict_json(args.policy.read_bytes())
    policy["compatibility"].update(
        executor_version="1.24.0-rc2",
        minimum_preparer_version="1.24.0",
    )
    args.policy.write_bytes(canonical_json(policy))
    args.output_dir = args.output_dir.with_name("unpreparable")
    with pytest.raises(ValueError, match="newer preparer"):
        build(args)
    assert not args.output_dir.exists()



def test_inventory_keeps_predecessor_infrastructure_leaves(tmp_path, monkeypatch):
    upstream = "registry.example.test/dvt"
    product_digest = "sha256:" + "1" * 64
    infrastructure = {
        "postgres": "docker.io/library/postgres@sha256:" + "2" * 64,
        "valkey": "docker.io/valkey/valkey@sha256:" + "3" * 64,
    }
    args = SimpleNamespace(
        references=None, infrastructure=tmp_path / "infra.json", metadata=tmp_path / "build.json",
        integration_lock=tmp_path / "integration.env", upstream=upstream, source=ROOT, scratch=tmp_path,
    )
    args.metadata.write_bytes(canonical_json({
        role: {"containerimage.digest": product_digest}
        for role in image_inventory.PRODUCT_ROLES
    }))
    args.infrastructure.write_bytes(canonical_json(infrastructure))
    monkeypatch.setattr(image_inventory, "git", lambda *_: (ROOT / COMPOSE).read_bytes())
    monkeypatch.setattr(image_inventory, "leaf_reference", lambda ref, _: ref)
    monkeypatch.setattr(image_inventory, "measure", lambda *_: (1, 1, 1))
    inventory = image_inventory.build_inventory(args, "auth")
    assert {role: inventory[role]["reference"] for role in infrastructure} == infrastructure
    assert inventory["migrate"] == inventory["gateway"]


def _cached_inventory(package, tmp_path, monkeypatch):
    release, images = package
    references = tmp_path / "references.json"
    references.write_bytes(canonical_json({role: image["reference"] for role, image in images.items()}))
    args = SimpleNamespace(
        references=references, infrastructure=None, scratch=tmp_path,
        previous_manifest=release.output_dir / "manifest.json", trust=release.trust,
    )
    resolved, copied = [], []

    def leaf(reference, _auth):
        resolved.append(reference)
        return reference

    def measure(reference, _auth, _directory):
        copied.append(reference)
        return 123, 456, 7

    monkeypatch.setattr(image_inventory, "leaf_reference", leaf)
    monkeypatch.setattr(image_inventory, "measure", measure)
    return args, resolved, copied


def _resign_cache(package, change):
    args, _ = package
    path = args.output_dir / "manifest.json"
    envelope = strict_json(path.read_bytes())
    change(envelope["payload"])
    key = strict_json(args.signer.read_bytes())["private_key"]
    signer = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key))
    envelope["manifest_signature"] = signer.sign(
        MANIFEST_CONTEXT + canonical_json(envelope["payload"])
    ).hex()
    path.write_bytes(canonical_json(envelope))


def test_inventory_reuses_signed_leaf_budgets_across_repositories(package, tmp_path, monkeypatch):
    args, resolved, copied = _cached_inventory(package, tmp_path, monkeypatch)
    references = strict_json(args.references.read_bytes())
    references["ui"] = "mirror.example.test/other-ui@sha256:" + "1" * 64
    references["proxy"] = "mirror.example.test/proxy@sha256:" + "2" * 64
    args.references.write_bytes(canonical_json(references))
    inventory = image_inventory.build_inventory(args, "auth")
    assert set(resolved) == set(references.values())
    assert copied == [references["proxy"]]
    assert inventory["ui"] == {
        "reference": references["ui"],
        "compressed_bytes": 1, "unpacked_bytes": 1, "unpacked_inodes": 1,
    }
    assert inventory["proxy"]["compressed_bytes"] == 123
    assert inventory["migrate"] == inventory["gateway"]


@pytest.mark.parametrize("problem", [
    "no_cache", "missing", "missing_trust", "no_trust", "invalid_trust", "unknown_root",
    "revoked", "expired", "tampered", "malformed", "oversize", "legacy_inventory",
    "wrong_platform", "conflicting_budgets",
])
def test_inventory_remeasures_untrusted_or_unusable_cache(
    package, tmp_path, monkeypatch, problem,
):
    args, resolved, copied = _cached_inventory(package, tmp_path, monkeypatch)
    if problem == "no_cache":
        args.previous_manifest = None
    elif problem == "missing":
        args.previous_manifest = tmp_path / "missing.json"
    elif problem == "missing_trust":
        args.trust = tmp_path / "missing-trust.json"
    elif problem == "no_trust":
        args.trust = None
    elif problem in {"invalid_trust", "unknown_root", "revoked"}:
        document = strict_json(args.trust.read_bytes())
        if problem == "invalid_trust":
            document = []
        elif problem == "unknown_root":
            document["roots"] = {"other": next(iter(document["roots"].values()))}
        else:
            signer = strict_json(args.previous_manifest.read_bytes())["signing_key"]["public_key"]
            document["revoked_signers"] = [digest_of(bytes.fromhex(signer))]
        args.trust.write_bytes(canonical_json(document))
    elif problem == "expired":
        _resign_cache(package, lambda value: value.update(
            issued_at=f"{datetime.now(UTC).year - 1}-01-01T00:00:00Z",
            expires_at=f"{datetime.now(UTC).year}-01-01T00:00:00Z",
        ))
    elif problem == "tampered":
        content = strict_json(args.previous_manifest.read_bytes())
        content["payload"]["platforms"]["linux/amd64"]["images"]["ui"]["unpacked_bytes"] = 999
        args.previous_manifest.write_bytes(canonical_json(content))
    elif problem == "malformed":
        args.previous_manifest.write_bytes(b'{"broken":')
    elif problem == "oversize":
        args.previous_manifest.write_bytes(b" " * (image_inventory.MAX_MANIFEST_BYTES + 1))
    elif problem == "legacy_inventory":
        args.previous_manifest.write_bytes(canonical_json(package[1]))
    elif problem == "wrong_platform":
        def change(value):
            value["platforms"] = {"linux/arm64": value["platforms"]["linux/amd64"]}
        _resign_cache(package, change)
    elif problem == "conflicting_budgets":
        def change(value):
            value["platforms"]["linux/amd64"]["images"]["ui"]["unpacked_bytes"] = 999
        _resign_cache(package, change)
    inventory = image_inventory.build_inventory(args, "auth")
    # One digest shared by all repositories is measured once, including the first delivery.
    assert len(copied) == 1
    assert resolved
    assert all(
        (image["compressed_bytes"], image["unpacked_bytes"], image["unpacked_inodes"])
        == (123, 456, 7)
        for image in inventory.values()
    )


def test_cache_does_not_hide_current_registry_resolution_failure(package, tmp_path, monkeypatch):
    args, _, copied = _cached_inventory(package, tmp_path, monkeypatch)

    def fail(*_):
        raise ValueError("Current Registry digest mismatch")

    monkeypatch.setattr(image_inventory, "leaf_reference", fail)
    with pytest.raises(ValueError, match="Current Registry"):
        image_inventory.build_inventory(args, "auth")
    assert copied == []


PROJECT_RELEASE = """
[project]
version = "1.24.0rc8"

[tool.dvt.release]
manifest_ttl_days = 180
minimum_preparer_version = "1.24.0-rc8"
journal_format = 1
initial_install = true
from_releases = []
required_extensions = []

[tool.dvt.release.environment]
distributions = { debian = ["13"], ubuntu = ["24.04"] }
min_docker = "29.0.0"
min_compose = "2.30.0"
pull_parallelism = 2

[tool.dvt.release.environment.base]
min_cpus = 2
min_ram_bytes = 4000000000
docker_reserve_bytes = 1073741824
data_reserve_bytes = 536870912
temporary_bytes = 2147483648
reserve_inodes = 100000
max_task_workers = 1

[tool.dvt.release.environment.profiles.ai-mcp]
min_cpus = 2
min_ram_bytes = 4000000000
docker_reserve_bytes = 1073741824
data_reserve_bytes = 536870912
temporary_bytes = 2147483648
reserve_inodes = 100000
max_task_workers = 1
"""
MIGRATIONS = {
    "start.py": b"revision='0001'\ndown_revision=None",
    "target.py": b"revision='f00d'\ndown_revision='0001'",
}


def _migration_archive(files):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name, content in files.items():
            info = tarfile.TarInfo("migrations/versions/" + name)
            info.size = len(content)
            stream.addfile(info, io.BytesIO(content))
    return archive.getvalue()


@pytest.fixture
def project_release(package, tmp_path, monkeypatch):
    args, images = package
    source = PROJECT_RELEASE
    source_version = tomllib.loads(source)["project"]["version"]
    snapshot = {"project": source, "archive": _migration_archive(MIGRATIONS)}
    for role, service in yaml.safe_load((ROOT / COMPOSE).read_bytes())["services"].items():
        images[role]["reference"] = source_repository(service["image"]) + "@sha256:" + "1" * 64
    args.images.write_bytes(canonical_json(images))
    args.backend_sha = args.ui_sha = None
    args.isolated = False
    args.policy = None
    args.version = "1.24.0-rc8"
    args.output_dir = tmp_path / "project-release"

    def git_snapshot(path, *command):
        if command == ("rev-parse", "HEAD"):
            return (("b" if Path(path).name == "ui" else "a") * 40 + "\n").encode()
        if command == ("ls-tree", "a" * 40, "services/ui"):
            return ("160000 commit " + "b" * 40 + "\tservices/ui\n").encode()
        if command == ("archive", "a" * 40, "migrations/versions"):
            return snapshot["archive"]
        if command[0] == "show":
            relative = command[1].partition(":")[2]
            if relative == "pyproject.toml":
                return snapshot["project"].encode("utf-8")
            return (ROOT / relative).read_bytes()
        raise AssertionError(command)

    monkeypatch.setattr(build_manifest, "git", git_snapshot)
    return args, snapshot, source_version


def _project_cli(args, monkeypatch, *extra):
    command = [
        "build_manifest", "--release-id", args.release_id, "--asset-origin", args.asset_origin,
        "--source", str(args.source), "--images", str(args.images),
        "--signer", str(args.signer), "--trust", str(args.trust),
        "--output-dir", str(args.output_dir),
    ]
    monkeypatch.setattr(sys, "argv", [*command, *extra])
    return build_manifest.main()


@pytest.mark.parametrize("version", ["1.24.0rc8", "1.24.0rc9", "1.24.0"])
def test_project_policy_cli_rc_to_rc_to_stable_without_policy_file(
    project_release, monkeypatch, version,
):
    args, snapshot, original = project_release
    snapshot["project"] = snapshot["project"].replace(f'version = "{original}"', f'version = "{version}"', 1)
    assert _project_cli(args, monkeypatch, "--version", version) == 0
    manifest = acceptance.verified_manifest((args.output_dir / "manifest.json").read_bytes(), args.trust)
    expected = build_manifest.normalized_version(version)
    assert manifest.version == expected
    assert manifest.channel == ("rc" if "rc" in version else "stable")
    assert manifest.backend_sha == "a" * 40 and manifest.ui_sha == "b" * 40
    assert manifest.compatibility.manager_version == expected
    assert manifest.compatibility.executor_version == expected
    assert manifest.compatibility.minimum_preparer_version == "1.24.0-rc8"
    assert manifest.database_schema.target_revision == "f00d"
    assert manifest.database_schema.initial_install and manifest.database_schema.from_releases == []
    assert datetime.fromisoformat(manifest.expires_at) - datetime.fromisoformat(manifest.issued_at) == timedelta(days=180)


@pytest.mark.parametrize("ttl", [180, 181, 10**100])
def test_project_cli_derives_version_without_tag_and_caps_certificate(project_release, monkeypatch, ttl):
    args, snapshot, _ = project_release
    snapshot["project"] = snapshot["project"].replace("manifest_ttl_days = 180", f"manifest_ttl_days = {ttl}")
    signer = strict_json(args.signer.read_bytes())
    # Keep the issued fixture's root certification authentic after shortening its validity.
    root = Ed25519PrivateKey.generate()
    trust = strict_json(args.trust.read_bytes())
    trust["roots"][signer["signing_key"]["root_id"]] = root.public_key().public_bytes_raw().hex()
    args.trust.write_bytes(canonical_json(trust))
    expiry = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
    signer["signing_key"]["valid_until"] = expiry.isoformat().replace("+00:00", "Z")
    signer["key_signature"] = root.sign(KEY_CONTEXT + canonical_json(signer["signing_key"])).hex()
    args.signer.write_bytes(canonical_json(signer))
    assert _project_cli(args, monkeypatch) == 0
    manifest = acceptance.verified_manifest((args.output_dir / "manifest.json").read_bytes(), args.trust)
    assert datetime.fromisoformat(manifest.expires_at) == expiry


@pytest.mark.parametrize("failure", [
    "tag", "multiple-heads", "syntax", "ttl", "missing-minimum", "expired", "future", "revoked",
])
def test_project_release_cli_refuses_invalid_inputs_before_writing(project_release, monkeypatch, failure):
    args, snapshot, _ = project_release
    extra = []
    if failure == "tag":
        extra = ["--version", "9.0.0"]
    elif failure == "multiple-heads":
        monkeypatch.setattr(build_manifest, "source_head", lambda *_: build_manifest.migration_head([
            b"revision='one'\ndown_revision=None",
            b"revision='two'\ndown_revision=None",
        ]))
    elif failure == "syntax":
        monkeypatch.setattr(build_manifest, "source_head", lambda *_: build_manifest.migration_head([
            b"revision =",
        ]))
    elif failure == "ttl":
        snapshot["project"] = snapshot["project"].replace("manifest_ttl_days = 180", "manifest_ttl_days = 0")
    elif failure == "missing-minimum":
        snapshot["project"] = snapshot["project"].replace('minimum_preparer_version = "1.24.0-rc8"\n', "")
    else:
        signer = strict_json(args.signer.read_bytes())
        if failure == "revoked":
            trust = strict_json(args.trust.read_bytes())
            trust["revoked_signers"] = [digest_of(bytes.fromhex(signer["signing_key"]["public_key"]))]
            args.trust.write_bytes(canonical_json(trust))
        else:
            key = "valid_until" if failure == "expired" else "valid_from"
            delta = -timedelta(days=1) if failure == "expired" else timedelta(days=1)
            signer["signing_key"][key] = (datetime.now(UTC) + delta).isoformat(timespec="seconds").replace("+00:00", "Z")
            args.signer.write_bytes(canonical_json(signer))
    assert _project_cli(args, monkeypatch, *extra) == 1
    assert not args.output_dir.exists()


def test_project_policy_uses_committed_pyproject_and_migrations(project_release, tmp_path, monkeypatch):
    args, _, _ = project_release
    dirty = tmp_path / "dirty-source"
    dirty.mkdir()
    (dirty / "pyproject.toml").write_text('[project]\nversion="99.0.0"\n', encoding="utf-8")
    args.source = dirty
    assert _project_cli(args, monkeypatch) == 0
    manifest = acceptance.verified_manifest((args.output_dir / "manifest.json").read_bytes(), args.trust)
    assert manifest.version == "1.24.0-rc8"
    assert manifest.database_schema.target_revision == "f00d"


def test_migration_graph_reads_literals_without_backend_imports():
    assert build_manifest.migration_head([
        b"import unavailable_backend\nrevision: str = 'one'\ndown_revision = None",
        b"raise RuntimeError('must not execute')\nrevision = 'two'\ndown_revision = 'one'",
        b"revision='branch'\ndown_revision='one'",
        b"revision='merged'\ndown_revision=('two', 'branch')\ndepends_on=None",
    ]) == "merged"


@pytest.mark.parametrize("files", [
    [b"revision='one'\ndown_revision=None", b"revision='one'\ndown_revision=None"],
    [b"revision='one'\ndown_revision='missing'"],
    [b"revision='one'\ndown_revision='two'", b"revision='two'\ndown_revision='one'"],
    [b"revision=execute_backend()\ndown_revision=None"],
])
def test_migration_graph_refuses_ambiguous_missing_or_dynamic_metadata(files):
    with pytest.raises((ValueError, RuntimeError)):
        build_manifest.migration_head(files)


@pytest.mark.parametrize("version", ["1.24.0rc8", "1.24.0rc9", "1.24.0"])
def test_release_subprocess_cli_uses_same_source_policy_for_rc_and_stable(
    package, tmp_path, version,
):
    args, _ = package
    source = tmp_path / "source"
    source.mkdir()
    project = PROJECT_RELEASE
    original = tomllib.loads(project)["project"]["version"]
    (source / "pyproject.toml").write_text(
        project.replace(f'version = "{original}"', f'version = "{version}"', 1), encoding="utf-8",
    )
    for name in (COMPOSE, BOOTSTRAP):
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for name, content in MIGRATIONS.items():
        path = source / "migrations/versions" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    output = tmp_path / "cli-package"
    result = subprocess.run([
        sys.executable, "-m", "scripts.release.build_manifest", "--source", str(source),
        "--isolated", "--backend-sha", "a" * 40, "--ui-sha", "b" * 40,
        "--release-id", "subprocess-source-policy", "--asset-origin", args.asset_origin,
        "--images", str(args.images), "--signer", str(args.signer), "--trust", str(args.trust),
        "--output-dir", str(output),
    ], env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    content = (output / "manifest.json").read_bytes()
    assert result.stdout.strip() == digest_of(content)
    manifest = acceptance.verified_manifest(content, args.trust)
    assert manifest.version == build_manifest.normalized_version(version)
    assert manifest.compatibility.minimum_preparer_version == "1.24.0-rc8"
    assert manifest.database_schema.target_revision == "f00d"


def test_source_head_archive_and_directory_use_same_nonrecursive_depth(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations/versions"
    migrations.mkdir(parents=True)
    files = {
        "current.py": b"revision='0070'\ndown_revision=None",
        "nested/ignored.py": b"revision='unsupported'\ndown_revision=None",
    }
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name, content in files.items():
            path = migrations / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            info = tarfile.TarInfo("migrations/versions/" + name)
            info.size = len(content)
            stream.addfile(info, io.BytesIO(content))
    monkeypatch.setattr(build_manifest, "git", lambda *_: archive.getvalue())
    assert build_manifest.source_head(tmp_path, None) == "0070"
    assert build_manifest.source_head(tmp_path, "a" * 40) == "0070"

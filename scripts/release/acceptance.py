"""Validate protected VM acceptance evidence and issue an exact-manifest receipt."""

import argparse
import math
import re
import sys
from pathlib import Path

from packaging.version import Version

from services.installation_manager.domain.operation_state import ReleasePin
from services.installation_manager.domain.release_manifest import (
    ReleaseManifest,
    SignedRelease,
    canonical_json,
    digest_of,
    strict_json,
)
from services.installation_manager.infrastructure.release_verification import (
    MAX_MANIFEST_BYTES,
    TrustPolicy,
)

from .build_manifest import https_origin, write_once

REQUIRED_CHECKS = {
    "AT-01": {"clean_docker_install", "cold_install_browser", "repeat_bootstrap", "conflict"},
    "AT-02": {"transient_tls", "bad_certificate", "registry_outage", "compose_timeout", "reduced_mtu"},
    "AT-03": {"docker_space", "containerd_inodes", "data_space", "backup_space", "space_during_prepare"},
    "AT-04": {"full_compose", "manager_created", "manager_start_error", "same_address_and_id"},
    "AT-05": {"lost_post", "parallel_browser_cli", "manager_restart", "host_restart"},
    "AT-06": {"1.22.0_to_1.23.0", "1.23.0_to_1.24.0-rc2", "candidate_upgrade",
              "preserved_instance", "schema_workers_etl_mcp"},
    "AT-07": {"child_etl", "scheduled_etl", "long_task", "worker_loss"},
    "AT-08": {"before_migration", "during_migration", "extension_failure", "slow_gateway"},
    "AT-09": {"incompatible_downgrade", "separate_clean_restore", "restored_extension_etl"},
    "AT-10": {"saved_mcp_secret", "custom_settings", "functional_profiles"},
    "AT-11": {"incomplete_release", "changed_latest", "bad_signature", "rc", "catalog_outage"},
    "AT-12": {"network_disabled", "offline_install", "offline_update", "offline_recovery"},
    "AT-13": {"unauthorized", "pairing_replay_expiry", "redacted_support", "initial_setup"},
}
METRICS = {
    "AT-01": {"actions", "ssh_sessions", "seconds_to_login"},
    "AT-05": {"resume_attempts", "automatic_resumes"},
    "AT-06": {"actions", "ssh_sessions", "prepare_seconds", "download_seconds",
              "maintenance_seconds", "unavailable_seconds"},
    "AT-09": {"restore_seconds", "rpo_seconds"},
}
REQUIRED_SYSTEMS = {("debian", "13"), ("ubuntu", "24.04")}
SAFE_EVIDENCE_FILE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,90}\.(?:txt|json|md)")


def verified_manifest(content: bytes, trust_file: Path) -> ReleaseManifest:
    if len(content) > MAX_MANIFEST_BYTES:
        raise ValueError("Release manifest exceeds its permitted size")
    payload = SignedRelease.model_validate(strict_json(content)).payload
    trust = TrustPolicy.from_document(strict_json(trust_file.read_bytes()))
    pin = ReleasePin(release_id=payload.release_id, manifest_digest=digest_of(content))
    return trust.verify(content, pin)


def check_metrics(case_id: str, metrics: dict) -> None:
    if set(metrics) != METRICS.get(case_id, set()):
        raise ValueError(f"Incomplete measurements for {case_id}")
    for name, value in metrics.items():
        is_count = name in {"actions", "ssh_sessions", "resume_attempts", "automatic_resumes"}
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (
            is_count and type(value) is not int
        ):
            raise ValueError(f"Invalid measurement for {case_id}")
    if case_id == "AT-05" and not (
        0 <= metrics["automatic_resumes"] <= metrics["resume_attempts"]
        and metrics["resume_attempts"] > 0
    ):
        raise ValueError("Invalid continuation measurements")


def check_case(
    case_id: str, case: dict, evidence_dir: Path, vm: str, release: ReleaseManifest,
) -> None:
    expected_fields = {"checks", "metrics", "evidence"}
    if case_id == "AT-09":
        expected_fields.add("restore_target")
    if set(case) != expected_fields or case["checks"] != dict.fromkeys(
        REQUIRED_CHECKS[case_id], "PASS"
    ):
        raise ValueError(f"Missing or unsuccessful checks for {case_id}")
    check_metrics(case_id, case["metrics"])
    if case_id == "AT-09":
        restore = case["restore_target"]
        if (
            set(restore) != {
                "vm", "distribution", "distribution_version", "platform", "compose_version",
                "docker_version",
            }
            or not isinstance(restore["vm"], str)
            or not restore["vm"].strip()
            or restore["vm"] == vm
            or restore["distribution_version"] not in release.environment.distributions.get(
                restore["distribution"], ()
            )
            or restore["platform"] not in release.platforms
            or Version(restore["compose_version"]) < Version(release.environment.min_compose)
            or Version(restore["docker_version"]) < Version(release.environment.min_docker)
        ):
            raise ValueError("Restore evidence requires a separate clean supported VM")
    evidence = case["evidence"]
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError(f"Evidence is missing for {case_id}")
    for name, digest in evidence.items():
        if not SAFE_EVIDENCE_FILE.fullmatch(name):
            raise ValueError("Evidence must use a simple text filename")
        path = evidence_dir / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 2 * 1024 * 1024:
            raise ValueError(f"Missing or oversized sanitized evidence for {case_id}")
        if digest_of(path.read_bytes()) != digest:
            raise ValueError(f"Evidence digest mismatch for {case_id}")


def issue_receipt(
    content: bytes, release: ReleaseManifest, matrix: dict, evidence_dir: Path, pipeline_id: str,
) -> dict:
    digest = digest_of(content)
    if (
        set(matrix) != {"format_version", "manifest_digest", "pipeline_id", "candidate_origin", "runs"}
        or type(matrix["format_version"]) is not int
        or matrix["format_version"] != 1
        or matrix["manifest_digest"] != digest
        or matrix["pipeline_id"] != pipeline_id
        or not re.fullmatch(r"[1-9][0-9]*", pipeline_id)
    ):
        raise ValueError("Matrix evidence must bind to this pipeline and exact envelope")
    origin = https_origin(matrix["candidate_origin"])
    if origin == "https://dvt.distribution.denvic.tech":
        raise ValueError("Acceptance must use an isolated candidate catalog")

    declared_systems = {
        (distribution, version)
        for distribution, versions in release.environment.distributions.items()
        for version in versions
    }
    if not declared_systems >= REQUIRED_SYSTEMS or declared_systems - REQUIRED_SYSTEMS - {
        ("debian", "12")
    } or set(release.platforms) != {"linux/amd64"}:
        raise ValueError("The release is outside the supported acceptance matrix")
    expected = {(*system, platform) for system in declared_systems for platform in release.platforms}
    observed = set()
    covered_cases = set()
    for run in matrix["runs"]:
        if set(run) != {
            "vm", "distribution", "distribution_version", "platform", "compose_version",
            "docker_version", "images", "cases",
        } or not isinstance(run["vm"], str) or not run["vm"].strip():
            raise ValueError("Invalid VM evidence fields")
        key = run["distribution"], run["distribution_version"], run["platform"]
        if key not in expected or key in observed:
            raise ValueError("Unexpected or duplicate VM profile")
        observed.add(key)
        if (
            Version(run["compose_version"]) < Version(release.environment.min_compose)
            or Version(run["docker_version"]) < Version(release.environment.min_docker)
        ):
            raise ValueError("The tested environment is outside the release toolchain policy")
        images = {role: entry.reference for role, entry in release.platforms[key[-1]].images.items()}
        base_images = {role: ref for role, ref in images.items() if role != "dvt-ai-mcp"}
        if run["images"] not in (images, base_images):
            raise ValueError("The VM profile lacks the signed image set")
        if "AT-01" not in run["cases"] or run["cases"].keys() - REQUIRED_CHECKS.keys():
            raise ValueError("Every declared VM profile needs AT-01")
        for case_id, case in run["cases"].items():
            if case_id != "AT-01" and case == pending_case(case_id):
                continue
            if case_id in {"AT-06", "AT-10"} and (
                "dvt-ai-mcp" not in images or run["images"] != images
            ):
                raise ValueError(f"{case_id} requires the signed AI MCP profile")
            check_case(case_id, case, evidence_dir, run["vm"], release)
            covered_cases.add(case_id)
    if observed != expected:
        raise ValueError("Evidence is missing for a declared VM profile")
    if covered_cases != REQUIRED_CHECKS.keys():
        raise ValueError("The matrix is missing required AT cases")
    return {
        "format_version": 1,
        "version": release.version,
        "manifest_digest": digest,
        "result": "passed",
        "run_id": f"gitlab-pipeline-{pipeline_id}",
    }


def pending_case(case_id: str) -> dict:
    case = {
        "checks": dict.fromkeys(REQUIRED_CHECKS[case_id], "NOT_RUN"),
        "metrics": dict.fromkeys(METRICS.get(case_id, set())),
        "evidence": {},
    }
    if case_id == "AT-09":
        case["restore_target"] = {}
    return case


def matrix_template(content: bytes, release: ReleaseManifest, pipeline_id: str, origin: str) -> dict:
    runs = []
    for platform in release.platforms:
        for distribution, versions in release.environment.distributions.items():
            for version in versions:
                runs.append({
                    "vm": "",
                    "distribution": distribution,
                    "distribution_version": version,
                    "platform": platform,
                    "compose_version": "",
                    "docker_version": "",
                    "images": {},
                    "cases": {case_id: pending_case(case_id) for case_id in REQUIRED_CHECKS},
                })
    return {
        "format_version": 1, "manifest_digest": digest_of(content), "pipeline_id": pipeline_id,
        "candidate_origin": https_origin(origin), "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "trust", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--pipeline-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--matrix", type=Path, help="Validate collected evidence and create receipt")
    mode.add_argument("--template", metavar="CANDIDATE_ORIGIN", help="Create a blank matrix")
    args = parser.parse_args()
    try:
        content = args.manifest.read_bytes()
        release = verified_manifest(content, args.trust)
        if args.template:
            template = matrix_template(content, release, args.pipeline_id, args.template)
            write_once(args.output, canonical_json(template))
            return 0
        receipt = issue_receipt(
            content, release, strict_json(args.matrix.read_bytes()), args.matrix.parent,
            args.pipeline_id,
        )
        write_once(args.output, canonical_json(receipt))
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, OverflowError, RecursionError):
        print("No readiness receipt: exact candidate and successful full VM evidence are required",
              file=sys.stderr)
        return 1
    print(receipt["manifest_digest"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

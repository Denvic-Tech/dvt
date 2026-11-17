from dataclasses import asdict

from src.modules.extension_management.infra.catalog import runtime_target


def release_payload(version: str, dvt_version: str | None = "*", url: str | None = None) -> dict:
    return {
        "version": version,
        "channel": "rc" if "rc" in version else "stable",
        "dvt_version": dvt_version,
        "target": asdict(runtime_target()),
        "size_bytes": 123,
        "sha256": "a" * 64,
        "download_url": url or f"https://example/{version}.dvtx",
    }


def extension_payload(name: str, versions: list[dict]) -> dict:
    return {"name": name, "display_name": name, "description": "", "versions": versions}

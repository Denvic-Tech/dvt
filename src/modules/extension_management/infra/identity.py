"""Resolve persisted identities identically for management, state and storage."""
from collections.abc import Iterable

from src.modules.extension_management.domain.policies import (
    extension_identity_set,
    normalize_extension_identity,
)
from src.modules.extension_management.infra.db_models import ExtensionRecord


def record_identities(record: ExtensionRecord) -> frozenset[str]:
    payload = record.manifest_json or {}
    return extension_identity_set(
        record.name, payload.get("package_name"),
        aliases=payload.get("legacy_names") or (),
    )


def resolve_record(
    records: Iterable[ExtensionRecord], name: str,
) -> ExtensionRecord | None:
    identity = normalize_extension_identity(name)
    matches = [record for record in records if identity in record_identities(record)]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous extension identity '{name}'")
    return matches[0] if matches else None


def manifest_with_aliases(record: ExtensionRecord, payload: dict) -> dict:
    result = dict(payload)
    result["name"] = record.name
    result["legacy_names"] = sorted({
        *((record.manifest_json or {}).get("legacy_names") or ()),
        *(payload.get("legacy_names") or ()),
    } - {record.name})
    return result

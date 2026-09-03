from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from db_connection.domain import ConnectionDraft, ConnectionRecord


def _to_dict(value: object, *, field_name: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if value is None:
        return {} if default is None else dict(default)
    if isinstance(value, Mapping):
        return dict(value)

    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError(f"Connection field '{field_name}' must be mapping-like, got {type(value)!r}.") from exc


def normalize_connection_record_for_validation(record: object) -> ConnectionDraft | ConnectionRecord:
    if isinstance(record, (ConnectionDraft, ConnectionRecord)):
        return record

    if isinstance(record, Mapping):
        required_fields = ("name", "kind", "type", "properties")
        missing_fields = [field for field in required_fields if field not in record]
        if missing_fields:
            missing_fields_str = ", ".join(sorted(missing_fields))
            raise TypeError(
                f"Connection mapping must define fields [{missing_fields_str}] "
                "for runtime validation."
            )

        return ConnectionDraft(
            name=record["name"],
            kind=record["kind"],
            type=record["type"],
            driver=record.get("driver"),
            driver_options=record.get("driver_options"),
            properties=_to_dict(record.get("properties"), field_name="properties"),
            secrets=_to_dict(record.get("secrets"), field_name="secrets"),
            labels=_to_dict(record.get("labels"), field_name="labels"),
            metadata=_to_dict(record.get("metadata"), field_name="metadata"),
            extra=_to_dict(record.get("extra"), field_name="extra"),
        )

    required_fields = ("name", "kind", "type", "properties")
    missing_fields = [field for field in required_fields if not hasattr(record, field)]
    if missing_fields:
        missing_fields_str = ", ".join(sorted(missing_fields))
        raise TypeError(
            f"Connection object must define fields [{missing_fields_str}] for runtime validation, "
            f"got {type(record)!r}."
        )

    return ConnectionDraft(
        name=getattr(record, "name"),
        kind=getattr(record, "kind"),
        type=getattr(record, "type"),
        driver=getattr(record, "driver", None),
        driver_options=getattr(record, "driver_options", None),
        properties=_to_dict(getattr(record, "properties"), field_name="properties"),
        secrets=_to_dict(getattr(record, "secrets", None), field_name="secrets"),
        labels=_to_dict(getattr(record, "labels", None), field_name="labels"),
        metadata=_to_dict(getattr(record, "metadata", None), field_name="metadata"),
        extra=_to_dict(getattr(record, "extra", None), field_name="extra"),
    )

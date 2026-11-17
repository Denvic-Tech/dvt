from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..catalog_values import ProjectionStamp
from ..entities import ProjectCatalogProjection
from ..types import ProjectionStatus


def variables_fingerprint(variables: Mapping[str, Any] | None) -> str:
    """Детерминированный отпечаток переменных проекта: порядок ключей не влияет."""
    payload = json.dumps(
        dict(variables or {}),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_projection_current(
    stored: ProjectCatalogProjection | None,
    current: ProjectionStamp,
) -> bool:
    """Проекция актуальна, если успешна и совпадает по ревизии графа и версии семантики.

    Отпечаток переменных сравнивается только когда проекция от них зависит.
    """
    if stored is None or stored.status is not ProjectionStatus.OK:
        return False
    if stored.stamp.graph_revision != current.graph_revision:
        return False
    if stored.stamp.lineage_schema_version != current.lineage_schema_version:
        return False
    return not (
        stored.depends_on_project_variables
        and stored.stamp.variables_fingerprint != current.variables_fingerprint
    )

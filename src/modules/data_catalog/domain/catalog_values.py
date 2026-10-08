"""Value objects каталога сущностей (в дополнение к снэпшотам схемы в value_objects.py)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .exceptions import InvalidFieldReferenceError
from .types import DiagnosticReason, ViewerScope


@dataclass(frozen=True, slots=True)
class RawLocator:
    """Локатор так, как он задан в ноде или SQL, до нормализации."""

    table: str
    schema: str | None = None
    database: str | None = None


@dataclass(frozen=True, slots=True)
class PhysicalLocator:
    dialect: str
    host: str
    port: int | None
    database: str | None
    schema: str | None
    table: str


@dataclass(frozen=True, slots=True)
class ProjectionStamp:
    graph_revision: int
    variables_fingerprint: str
    lineage_schema_version: int


@dataclass(frozen=True, slots=True)
class ObservedField:
    name: str
    dtype: str | None = None
    nullable: bool | None = None
    ordinal: int | None = None
    primary_key: bool = False
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class SqlTableRef:
    table: str
    schema: str | None = None
    catalog: str | None = None


@dataclass(frozen=True, slots=True)
class SqlTableReferences:
    tables: tuple[SqlTableRef, ...] = ()
    cte_names: frozenset[str] = frozenset()
    used_project_variables: bool = False


@dataclass(frozen=True, slots=True)
class ProjectionDiagnostic:
    node_id: str
    node_name: str
    reason: DiagnosticReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogViewer:
    user_id: str
    organization_id: str | None
    scope: ViewerScope


@dataclass(frozen=True, slots=True)
class SchemaActor:
    id: str
    organization_id: str
    role: str


def _clean_ref(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


@dataclass(frozen=True, slots=True)
class FieldRef:
    """Ссылка на поле сущности: ровно одно из field_id или name."""

    field_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_id", _clean_ref(self.field_id))
        object.__setattr__(self, "name", _clean_ref(self.name))
        if (self.field_id is None) == (self.name is None):
            raise InvalidFieldReferenceError("Field reference must contain exactly one of field_id or name.")


@dataclass(frozen=True, slots=True)
class FieldDescriptionChange:
    """Изменение описания поля; description=None означает очистку."""

    description: str | None
    field_id: str | None = None
    name: str | None = None

    @property
    def ref(self) -> FieldRef:
        return FieldRef(field_id=self.field_id, name=self.name)


@dataclass(frozen=True, slots=True)
class ObservedNodeSchema:
    """Схема таблицы, наблюдённая Read-нодой во время прогона пайплайна."""

    project_id: str
    node_id: str
    connection_id: str
    connection_revision: str
    fields: tuple[ObservedField, ...]
    observed_at: datetime
    trust_types: bool
    partial: bool = False
    table: str | None = None
    schema: str | None = None
    database: str | None = None

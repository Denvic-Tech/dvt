"""Домен column-level lineage: ссылки на колонки, порты нод, документ проекта и read-модели.

Документ lineage живёт в проекции проекта и целиком пересобирается статическим проходом.
Ссылка `LineageRef` считается контрактом: к ней привязываются аннотации и термины глоссария.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .catalog_values import ProjectionDiagnostic
from .exceptions import InvalidLineageRefError
from .types import (
    LINEAGE_SCHEMA_VERSION,
    DiagnosticReason,
    ExplainDirection,
    LineageOp,
    LineageProvenance,
    PortStatus,
    RefKind,
    ResolvedVia,
    SqlColumnKind,
)

OUTPUT_ROLE = "output"
INPUT_ROLE = "input"


@dataclass(frozen=True, slots=True)
class LineageRef:
    """`ds:<dataset_id>:<field_id>` или `node:<node_id>:<port>:<column>`; колонка может содержать `:`."""

    kind: RefKind
    parts: tuple[str, ...]

    @property
    def key(self) -> str:
        return ":".join((self.kind.value, *self.parts))

    @classmethod
    def dataset_field(cls, dataset_id: str, field_id: str) -> LineageRef:
        return cls(RefKind.DATASET_FIELD, (dataset_id, field_id))

    @classmethod
    def node_column(cls, node_id: str, port: str, name: str) -> LineageRef:
        return cls(RefKind.NODE_COLUMN, (node_id, port, name))

    @classmethod
    def parse(cls, key: str) -> LineageRef:
        prefix, separator, rest = key.partition(":")
        if not separator or not rest:
            raise InvalidLineageRefError(f"Lineage reference {key!r} has no payload")
        try:
            kind = RefKind(prefix)
        except ValueError as exc:
            raise InvalidLineageRefError(f"Lineage reference {key!r} has unknown kind") from exc
        if kind is RefKind.DATASET_FIELD:
            parts = tuple(rest.split(":", 1))
            if len(parts) != 2 or not all(parts):
                raise InvalidLineageRefError(f"Dataset field reference {key!r} is malformed")
        else:
            parts = tuple(rest.split(":", 2))
            if len(parts) != 3 or not all(parts):
                raise InvalidLineageRefError(f"Node column reference {key!r} is malformed")
        return cls(kind, parts)

    @property
    def is_dataset_field(self) -> bool:
        return self.kind is RefKind.DATASET_FIELD

    @property
    def dataset_id(self) -> str | None:
        return self.parts[0] if self.is_dataset_field else None

    @property
    def field_id(self) -> str | None:
        return self.parts[1] if self.is_dataset_field else None

    @property
    def node_id(self) -> str | None:
        return None if self.is_dataset_field else self.parts[0]

    @property
    def port(self) -> str | None:
        return None if self.is_dataset_field else self.parts[1]

    @property
    def column(self) -> str | None:
        return None if self.is_dataset_field else self.parts[2]


@dataclass(frozen=True, slots=True)
class ColumnLineage:
    """Колонка порта: операция, зависимости и корневое происхождение.

    `details` хранит ключ шаблона объяснения и его параметры (только JSON-совместимые значения).
    `origin` заполняется при финализации порта; у колонки без известного единственного родителя
    по цепочке PASS/RENAME origin равен её собственной ссылке.
    """

    name: str
    op: LineageOp
    deps: tuple[LineageRef, ...] = ()
    deps_unknown: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
    origin: LineageRef | None = None

    def with_origin(self, origin: LineageRef) -> ColumnLineage:
        return ColumnLineage(
            name=self.name,
            op=self.op,
            deps=self.deps,
            deps_unknown=self.deps_unknown,
            details=self.details,
            origin=origin,
        )


@dataclass(frozen=True, slots=True)
class PortColumns:
    """Результат правила ноды для одного выходного порта до финализации."""

    columns: tuple[ColumnLineage, ...] = ()
    status: PortStatus = PortStatus.RESOLVED
    reason: DiagnosticReason | None = None
    detail: str | None = None

    @property
    def known(self) -> bool:
        return self.status is not PortStatus.UNRESOLVED

    @classmethod
    def unresolved(cls, reason: DiagnosticReason, detail: str | None = None) -> PortColumns:
        return cls(columns=(), status=PortStatus.UNRESOLVED, reason=reason, detail=detail)


@dataclass(frozen=True, slots=True)
class PortLineage:
    node_id: str
    node_name: str
    port: str
    status: PortStatus
    columns: tuple[ColumnLineage, ...] = ()
    role: str = OUTPUT_ROLE
    reason: DiagnosticReason | None = None
    detail: str | None = None

    @property
    def known(self) -> bool:
        return self.status is not PortStatus.UNRESOLVED

    def ref(self, name: str) -> LineageRef:
        return LineageRef.node_column(self.node_id, self.port, name)

    def column(self, name: str) -> ColumnLineage | None:
        for item in self.columns:
            if item.name == name:
                return item
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.columns)


@dataclass(frozen=True, slots=True)
class ProjectLineage:
    ports: tuple[PortLineage, ...] = ()
    version: int = LINEAGE_SCHEMA_VERSION
    truncated: bool = False

    @property
    def column_count(self) -> int:
        return sum(len(port.columns) for port in self.ports)


@dataclass(frozen=True, slots=True)
class NodePortTypes:
    """DataFrame- и Series-порты ноды и значения по умолчанию её входов."""

    dataframe_inputs: frozenset[str] = frozenset()
    dataframe_outputs: tuple[str, ...] = ()
    column_inputs: frozenset[str] = frozenset()
    column_outputs: tuple[str, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_dataframe_ports(self) -> bool:
        return bool(self.dataframe_inputs or self.dataframe_outputs)


@dataclass(frozen=True, slots=True)
class SourceSeedContext:
    """Что статический проход узнал о Read-ноде: сущности и, для SQL, текст запроса."""

    node_id: str
    node_name: str
    dataset_ids: tuple[str, ...]
    resolved_via: ResolvedVia
    references: Mapping[str, str] = field(default_factory=dict)
    sql: str | None = None
    dialect: str | None = None
    column_filter: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SqlSchemaHint:
    """reference (`catalog.schema.table` в нижнем регистре) → имена колонок сущности."""

    tables: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SqlSourceColumn:
    reference: str
    column: str


@dataclass(frozen=True, slots=True)
class SqlColumnLineage:
    name: str
    kind: SqlColumnKind
    sources: tuple[SqlSourceColumn, ...] = ()
    unknown_sources: bool = False
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class SqlLineageResult:
    columns: tuple[SqlColumnLineage, ...] = ()
    supported: bool = True
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedRuleColumn:
    source: str
    targets: tuple[str, ...]
    drops_source: bool = False
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedDescription:
    text: str | None
    provenance: LineageProvenance
    source: LineageRef | None = None


@dataclass(frozen=True, slots=True)
class NodeFieldView:
    name: str
    ref: LineageRef
    op: LineageOp
    origin: LineageRef
    deps: tuple[LineageRef, ...]
    deps_unknown: bool
    description: str | None
    provenance: LineageProvenance
    description_source: LineageRef | None
    explanation: str | None


@dataclass(frozen=True, slots=True)
class NodeFieldsResult:
    project_id: str
    node_id: str
    node_name: str
    port: str
    role: str
    status: PortStatus
    fields: tuple[NodeFieldView, ...]
    reason: DiagnosticReason | None = None
    detail: str | None = None
    available_ports: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExplainStep:
    ref: LineageRef
    depth: int
    op: LineageOp
    text: str | None
    node_id: str | None = None
    node_name: str | None = None
    port: str | None = None
    column: str | None = None
    deps_unknown: bool = False
    dataset_id: str | None = None
    field_id: str | None = None
    field_name: str | None = None
    deps: tuple[LineageRef, ...] = ()


@dataclass(frozen=True, slots=True)
class LineageGap:
    ref: LineageRef
    reason: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class FieldExplanation:
    root: LineageRef
    direction: ExplainDirection
    steps: tuple[ExplainStep, ...]
    gaps: tuple[LineageGap, ...] = ()
    description: ResolvedDescription | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class FieldDependent:
    project_id: str
    node_id: str
    node_name: str
    port: str
    column: str
    op: LineageOp
    depth: int
    ref: LineageRef


@dataclass(frozen=True, slots=True)
class LineageBuildResult:
    lineage: ProjectLineage | None
    diagnostics: tuple[ProjectionDiagnostic, ...] = ()

    @property
    def port_count(self) -> int:
        return len(self.lineage.ports) if self.lineage is not None else 0

    @property
    def column_count(self) -> int:
        return self.lineage.column_count if self.lineage is not None else 0


def column_names(columns: Sequence[ColumnLineage]) -> tuple[str, ...]:
    return tuple(item.name for item in columns)

from __future__ import annotations

from datetime import UTC, datetime

from src.modules.data_catalog.domain import (
    DatasetField,
    DiagnosticReason,
    FieldStatus,
    LineageOp,
    PortStatus,
    SqlColumnKind,
    SqlColumnLineage,
    SqlLineageResult,
    SqlSourceColumn,
)
from src.modules.data_catalog.domain.policies import build_schema_hint, sql_lineage_to_port_columns

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _field(dataset_id: str, name: str, status=FieldStatus.OK) -> DatasetField:
    return DatasetField(id=f"{dataset_id}-{name}", dataset_id=dataset_id, name=name, status=status, first_seen_at=NOW, last_seen_at=NOW)


FIELDS = {
    "d-orders": [_field("d-orders", "ID"), _field("d-orders", "amount"), _field("d-orders", "gone", FieldStatus.MISSING)],
    "d-cust": [_field("d-cust", "id")],
}
REFERENCES = {"public.orders": "d-orders", "customers": "d-cust"}


def test_schema_hint_skips_missing_fields_and_unknown_datasets():
    hint = build_schema_hint({**REFERENCES, "ghost": "d-none"}, FIELDS)
    assert hint.tables == {"public.orders": ("ID", "amount"), "customers": ("id",)}


def test_mapping_assigns_ops_refs_and_case_insensitive_matching_for_postgres():
    result = SqlLineageResult(
        columns=(
            SqlColumnLineage("id", SqlColumnKind.COLUMN, (SqlSourceColumn("public.orders", "id"),)),
            SqlColumnLineage("ident", SqlColumnKind.COLUMN, (SqlSourceColumn("customers", "id"),)),
            SqlColumnLineage("total", SqlColumnKind.AGGREGATE, (SqlSourceColumn("public.orders", "amount"),), expression="SUM(amount)"),
            SqlColumnLineage("both", SqlColumnKind.UNION, (SqlSourceColumn("public.orders", "amount"), SqlSourceColumn("customers", "id"))),
            SqlColumnLineage("lit", SqlColumnKind.LITERAL),
            SqlColumnLineage("lost", SqlColumnKind.COLUMN, (SqlSourceColumn("public.orders", "gone"),)),
            SqlColumnLineage("ext", SqlColumnKind.EXPRESSION, (SqlSourceColumn("other.table", "x"),), expression="x + 1"),
        )
    )
    port = sql_lineage_to_port_columns(result, REFERENCES, FIELDS, "postgresql")
    columns = {c.name: c for c in port.columns}

    assert port.status is PortStatus.PARTIALLY_RESOLVED
    assert columns["id"].op is LineageOp.PASS and columns["id"].deps[0].field_id == "d-orders-ID"
    assert columns["ident"].op is LineageOp.RENAME and columns["ident"].details["source"] == "id"
    assert columns["total"].op is LineageOp.AGGREGATE and columns["total"].details["expression"] == "SUM(amount)"
    assert columns["both"].op is LineageOp.MERGE and len(columns["both"].deps) == 2
    assert columns["lit"].op is LineageOp.COMPUTE and columns["lit"].deps == ()
    assert columns["lost"].deps_unknown is True, "missing field is not a valid source"
    assert columns["ext"].deps_unknown is True and columns["ext"].deps == ()


def test_case_sensitive_dialect_does_not_fold_names():
    result = SqlLineageResult(columns=(SqlColumnLineage("id", SqlColumnKind.COLUMN, (SqlSourceColumn("public.orders", "id"),)),))
    port = sql_lineage_to_port_columns(result, REFERENCES, FIELDS, "clickhouse")
    assert port.columns[0].deps_unknown is True


def test_unsupported_sql_gives_unresolved_port():
    port = sql_lineage_to_port_columns(SqlLineageResult(supported=False, error="parse: boom"), REFERENCES, FIELDS, "postgresql")
    assert port.status is PortStatus.UNRESOLVED and port.reason is DiagnosticReason.LINEAGE_SQL_UNSUPPORTED

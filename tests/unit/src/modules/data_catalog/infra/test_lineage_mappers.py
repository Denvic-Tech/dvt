from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    ColumnLineage,
    DiagnosticReason,
    LineageOp,
    LineageRef,
    PortLineage,
    PortStatus,
    ProjectLineage,
)
from src.modules.data_catalog.infra.lineage_mappers import lineage_from_json, lineage_to_json


def _lineage() -> ProjectLineage:
    source = LineageRef.dataset_field("ds", "f1")
    column = ColumnLineage(
        name="a:b",
        op=LineageOp.RENAME,
        deps=(LineageRef.node_column("r", "output", "a"),),
        details={"template": "lineage.rename", "source": "a"},
        origin=source,
    )
    port = PortLineage(node_id="n", node_name="DataFrameRenameColumns", port="output", status=PortStatus.RESOLVED, columns=(column,))
    unresolved = PortLineage(
        node_id="p", node_name="LoadParquet", port="output", status=PortStatus.UNRESOLVED,
        reason=DiagnosticReason.LINEAGE_SOURCE_NOT_STATIC, detail="no static schema",
    )
    return ProjectLineage(ports=(port, unresolved), truncated=True)


def test_document_round_trips():
    original = _lineage()
    restored = lineage_from_json(lineage_to_json(original))
    assert restored == original


def test_foreign_version_and_garbage_are_ignored():
    payload = lineage_to_json(_lineage())
    payload["version"] = LINEAGE_SCHEMA_VERSION + 1
    assert lineage_from_json(payload) is None
    assert lineage_from_json("not a dict") is None

    broken = lineage_to_json(_lineage())
    broken["ports"][0]["columns"].append({"name": "bad", "op": "pass", "deps": ["garbage"]})
    restored = lineage_from_json(broken)
    assert restored is not None and [c.name for c in restored.ports[0].columns] == ["a:b"]

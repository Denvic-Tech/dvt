import pytest

from src.modules.data_catalog.domain import InvalidLineageRefError, LineageRef, RefKind


def test_node_reference_round_trips_and_keeps_colons_in_column_name():
    ref = LineageRef.node_column("n1", "output", "a:b:c")
    assert ref.key == "node:n1:output:a:b:c"
    parsed = LineageRef.parse(ref.key)
    assert parsed == ref
    assert (parsed.node_id, parsed.port, parsed.column) == ("n1", "output", "a:b:c")
    assert parsed.dataset_id is None and parsed.is_dataset_field is False


def test_dataset_field_reference_round_trips():
    ref = LineageRef.dataset_field("ds-1", "f-1")
    parsed = LineageRef.parse("ds:ds-1:f-1")
    assert parsed == ref and parsed.kind is RefKind.DATASET_FIELD
    assert (parsed.dataset_id, parsed.field_id) == ("ds-1", "f-1")


@pytest.mark.parametrize("key", ["", "ds", "ds:", "ds:only", "node:n1:output", "x:a:b", "ds::f", "node:n::c"])
def test_malformed_references_are_rejected(key):
    with pytest.raises(InvalidLineageRefError):
        LineageRef.parse(key)

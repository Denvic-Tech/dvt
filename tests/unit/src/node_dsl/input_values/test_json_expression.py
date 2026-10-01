import json

import pytest

from core.hashing import get_hash

from src.node_dsl.core.input_values import NodeInputExpressionValue, resolve_node_input_value
from src.node_dsl.input_expressions import evaluate_input_expression
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import UnresolvedValue


@pytest.mark.parametrize("as_list", [False, True])
def test_json_expression_produces_independent_serializable_containers(as_list):
    payload = {"partitions": [{"partition": 0, "next_offset": 5}], "nullable": None}
    original = [payload] if as_list else payload
    kwargs = {"expression": "offsets", "variables": {"offsets": original}, "expression_kind": "single"}
    frozen = evaluate_input_expression(**kwargs)
    with pytest.raises(TypeError):
        (frozen[0] if as_list else frozen)["changed"] = True
    result = resolve_node_input_value(
        NodeInputExpressionValue(value="offsets", expression_kind="single"),
        variables={"offsets": original}, target_type=IO.JSON,
    )
    assert json.loads(json.dumps(result)) == original
    assert get_hash(result) == get_hash(original)
    resolved_payload = result[0] if as_list else result
    resolved_payload["partitions"][0]["next_offset"] = 9
    assert payload["partitions"][0]["next_offset"] == 5


def test_unresolved_json_remains_unresolved():
    value = UnresolvedValue()
    result = resolve_node_input_value(
        NodeInputExpressionValue(value="offsets", expression_kind="single"),
        variables={"offsets": value}, target_type=IO.JSON,
    )
    assert result is value

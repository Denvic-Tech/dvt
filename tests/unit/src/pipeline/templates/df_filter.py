from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def build_condition(column: str, operator: str, value=None) -> dict:
    right = None
    if operator not in {"isnull", "notnull"}:
        right = {"type": "literal", "value": value}

    return {
        "kind": "condition",
        "left": {"type": "column", "column": column},
        "operator": operator,
        "right": right,
    }


def get_filter(link_to_df, conditions, node_id="filter"):
    return {
        node_id: NodeData(
            name="DataFrameFilter",
            inputs={
                "df": NodeInputLinkValue(node_id=link_to_df, output_name="output"),
                "conditions": NodeInputConstantValue(value=conditions),
            },
        )
    }

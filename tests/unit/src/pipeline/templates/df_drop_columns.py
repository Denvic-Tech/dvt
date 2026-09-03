from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_drop_columns(link_to_df, columns, node_id="drop"):
    return {
        node_id: NodeData(
            name="DataFrameDropColumns",
            inputs={
                "df": NodeInputLinkValue(node_id=link_to_df, output_name="output"),
                "columns": NodeInputConstantValue(value=columns),
            },
        )
    }

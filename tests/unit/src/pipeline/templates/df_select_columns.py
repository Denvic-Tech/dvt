from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_select_columns(link_to_df, columns, node_id="select"):
    return {
        node_id: NodeData(
            name="DataFrameSelectColumns",
            inputs={
                "df": NodeInputLinkValue(node_id=link_to_df, output_name="output"),
                "columns": NodeInputConstantValue(value=columns),
            },
        )
    }

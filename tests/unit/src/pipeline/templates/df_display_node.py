from src.node_dsl.core.input_values import NodeInputLinkValue
from src.schemas.internal import NodeData


def get_display_node(node_id="display", link_to_dataframe_name="read_table"):
    return {
        node_id: NodeData(
            name="DataFrameDisplayNode",
            inputs={
                "df": NodeInputLinkValue(
                    node_id=link_to_dataframe_name,
                    output_name="output",
                )
            },
        )
    }

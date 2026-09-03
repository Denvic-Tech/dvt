from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_join(left_link_to_df, right_link_to_df, left_on, right_on, how="left", node_id="join"):
    return {
        node_id: NodeData(
            name="DataFrameJoin",
            inputs={
                "left": NodeInputLinkValue(node_id=left_link_to_df, output_name="output"),
                "right": NodeInputLinkValue(node_id=right_link_to_df, output_name="output"),
                "left_on": NodeInputConstantValue(value=left_on),
                "right_on": NodeInputConstantValue(value=right_on),
                "how": NodeInputConstantValue(value=how),
            },
        )
    }

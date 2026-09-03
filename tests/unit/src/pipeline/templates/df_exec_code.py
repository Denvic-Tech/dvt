from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_exec_code(link_to_df, code, node_id="exec_code"):
    return {
        node_id: NodeData(
            name="DataFrameExecCode",
            inputs={
                "df": NodeInputLinkValue(node_id=link_to_df, output_name="output"),
                "code": NodeInputConstantValue(value=code),
            },
        )
    }

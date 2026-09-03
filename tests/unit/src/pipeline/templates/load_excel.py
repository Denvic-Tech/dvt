from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_load_excel(connection, path="testing_folder/testing_file.xlsx", node_id="load_excel"):
    return {
        node_id: NodeData(
            name="LoadExcel",
            inputs={
                "connection": NodeInputConstantValue(value=connection),
                "path": NodeInputConstantValue(value=path),
            },
        )
    }

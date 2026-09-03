from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputConstantValue


def get_save_excel(connection, df, path="testing_folder/testing_file.xlsx", node_id="save_excel"):
    return {
        node_id: NodeData(
            name="SaveExcel",
            inputs={
                "connection": NodeInputConstantValue(value=connection),
                "df": NodeInputConstantValue(value=df),
                "path": NodeInputConstantValue(value=path),
            },
        )
    }

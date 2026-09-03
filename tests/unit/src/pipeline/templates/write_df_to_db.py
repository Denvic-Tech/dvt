from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_write_to_db(
    connection,
    df,
    table_name="test_columns_pipeline",
    index_col="col",
    write_mode="recreate",
    node_id="write_table",
):
    return {
        node_id: NodeData(
            name="WriteDataFrameToDB",
            inputs={
                "connection": NodeInputConstantValue(value=connection),
                "table_name": NodeInputConstantValue(value=table_name),
                "df": NodeInputConstantValue(value=df),
                "index_col": NodeInputConstantValue(value=index_col),
                "write_mode": NodeInputConstantValue(value=write_mode),
            },
        )
    }

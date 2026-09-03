from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue


def get_read_query(connection, query="SELECT * FROM test_columns_pipeline", node_id="read_query"):
    return {
        node_id: NodeData(
            name="ReadQueryFromDB",
            inputs={
                "connection": NodeInputConstantValue(value=connection),
                "query": NodeInputConstantValue(value=query),
                "index_col": NodeInputConstantValue(value=None),
            },
        )
    }

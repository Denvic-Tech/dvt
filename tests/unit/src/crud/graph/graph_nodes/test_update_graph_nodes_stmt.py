import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from src.crud.graph.graph_nodes.update import build_update_graph_nodes_stmt
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord


def test_build_update_graph_nodes_stmt_casts_boolean_columns_for_postgres() -> None:
    node_patch = GraphNodeRecord(
        id="358b3eed-49f4-4ec1-8a4b-d61f97da0261",
        ui_id="node_38e90344-bc06-48f6-9986-e2323f34a493",
        project_id="c985622e-2a54-4c69-941a-72bdb23e399f",
        user_id="548faa50-04ec-40f4-9476-32d8d87354d3",
        selected=False,
        input_values={
            "connection_id": {
                "__dvt_type": "const",
                "value": "d4de8a2f-86a8-44ce-9f1a-acde00000000",
            }
        },
        # store_enabled intentionally omitted to match patch semantics
    )

    dialect = postgresql.dialect()
    stmt = build_update_graph_nodes_stmt(nodes=[node_patch], dialect=dialect)

    sql = str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": False}))

    # Regression guard: without explicit casts Postgres can infer `v.store_enabled` as TEXT
    # and fail with `COALESCE types text and boolean cannot be matched`.
    assert "CAST(v.selected AS BOOLEAN)" in sql
    assert "CAST(v.store_enabled AS BOOLEAN)" in sql
    assert "CAST(v.show_signal_io AS BOOLEAN)" in sql

    # Sanity: ensure it's a Postgres UPDATE against graph_nodes.
    assert "UPDATE graph_nodes" in sql

    # Ensure we didn't accidentally change the target column type in assignment.
    assert isinstance(GraphNodeRecord.__table__.c.store_enabled.type, sa.Boolean)
    assert isinstance(GraphNodeRecord.__table__.c.show_signal_io.type, sa.Boolean)

from typing import Sequence
from datetime import datetime, UTC

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql.json import JSONB

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.constants import UNSET


empty_jsonb = sa.text("'{}'::jsonb")

# Колонки, для которых нужно различать "не передано" и "явно null".
_NULLABLE_COLUMNS = frozenset({"subgraph_id", "comment"})


def typed_value(value, col, dialect: sa.Dialect):
    # NULL::type (диалектно-специфичный тип можно взять через dialect_impl)
    coltype = col.type.dialect_impl(dialect)

    if value is None:
        return sa.cast(sa.null(), coltype)

    return sa.bindparam(None, value, type_=coltype)


def typed_value_nullable_aware(node_dict: dict, col, dialect: sa.Dialect):
    """
    Для nullable-колонок различает "не передано" (sentinel) и "явно null" (SQL NULL).
    Для остальных колонок — стандартное поведение через typed_value.
    """
    coltype = col.type.dialect_impl(dialect)

    if col.name not in node_dict:
        if col.name in _NULLABLE_COLUMNS:
            return sa.bindparam(None, UNSET, type_=coltype)
        return sa.cast(sa.null(), coltype)

    value = node_dict[col.name]
    if value is None:
        return sa.cast(sa.null(), coltype)

    return sa.bindparam(None, value, type_=coltype)


def _nullable_expr(v_col, t_col):
    """
    CASE WHEN v.col = sentinel THEN t.col   -- не передано, оставить старое
         ELSE v.col                          -- передано (включая NULL), записать
    END
    """
    return sa.case(
        (v_col == UNSET, t_col),
        else_=v_col,
    )


def build_update_graph_nodes_stmt(
    *,
    nodes: Sequence[GraphNodeRecord],
    dialect: sa.Dialect,
) -> sa.Update:
    """
    Build an UPDATE statement for batch patching graph nodes.

    Important: we explicitly cast boolean-ish columns from the VALUES subquery to BOOLEAN to avoid
    Postgres errors like `COALESCE types text and boolean cannot be matched` when `VALUES` column
    types are inferred unexpectedly.
    """
    t = GraphNodeRecord.__table__

    nodes_dict_data = [node.model_dump(exclude_unset=True) for node in nodes]

    nodes_data = [
        tuple(typed_value_nullable_aware(node_dict, col, dialect) for col in t.c)
        for node_dict in nodes_dict_data
    ]

    v = sa.values(*t.c, name="v").data(nodes_data).alias("v")

    return (
        sa.update(t)
        .where(
            sa.or_(
                t.c.id == v.c.id,
                t.c.ui_id == v.c.ui_id,
            ),
            t.c.project_id == v.c.project_id,
            t.c.user_id == v.c.user_id,
        )
        .values(
            type=sa.func.coalesce(v.c.type, t.c.type),
            position_x=sa.func.coalesce(sa.func.cast(v.c.position_x, sa.Float), t.c.position_x),
            position_y=sa.func.coalesce(sa.func.cast(v.c.position_y, sa.Float), t.c.position_y),
            selected=sa.func.coalesce(sa.cast(v.c.selected, sa.Boolean), t.c.selected),
            name=sa.func.coalesce(v.c.name, t.c.name),
            display_name=sa.func.coalesce(v.c.display_name, t.c.display_name),
            comment=_nullable_expr(v.c.comment, t.c.comment),
            store_enabled=sa.func.coalesce(sa.cast(v.c.store_enabled, sa.Boolean), t.c.store_enabled),
            show_signal_io=sa.func.coalesce(sa.cast(v.c.show_signal_io, sa.Boolean), t.c.show_signal_io),
            show_variables_io=sa.func.coalesce(sa.cast(v.c.show_variables_io, sa.Boolean), t.c.show_variables_io),
            input_values=sa.func.coalesce(
                sa.func.nullif(v.c.input_values, sa.cast(empty_jsonb, JSONB)),
                t.c.input_values,
            ),
            subgraph_id=_nullable_expr(v.c.subgraph_id, t.c.subgraph_id),
            updated_at=datetime.now(tz=UTC),
        )
        .returning(t.c.id, t.c.ui_id, t.c.type)
    )


async def update_graph_nodes(
    session: AsyncSession,
    nodes: Sequence[GraphNodeRecord],
) -> Sequence[sa.Row[GraphNodeRecord]]:
    stmt = build_update_graph_nodes_stmt(nodes=nodes, dialect=session.bind.dialect)

    res = (await session.execute(stmt)).all()

    return res

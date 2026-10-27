from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    ColumnDescriptionChange,
    ColumnLineage,
    LineageNodePortNotFoundError,
    LineageOp,
    LineageRef,
    NodeColumnAnnotation,
    PortLineage,
    PortStatus,
    ProjectLineage,
)
from src.modules.data_catalog.flow import SetNodeColumnDescriptions

from ..fakes import (
    FakeFreshness,
    FakeGraphGateway,
    InMemoryAnnotationRepository,
    InMemoryProjectionRepository,
)

NOW = datetime(2026, 10, 21, tzinfo=UTC)
SOURCE_REF = LineageRef.dataset_field("d1", "f-id")


def _lineage() -> ProjectLineage:
    passed = ColumnLineage("customer_id", LineageOp.PASS, (LineageRef.node_column("r", "output", "id"),), origin=SOURCE_REF)
    score = ColumnLineage(
        "score", LineageOp.COMPUTE, (LineageRef.node_column("e", "output", "customer_id"),),
        origin=LineageRef.node_column("e", "output", "score"),
    )
    return ProjectLineage(
        ports=(PortLineage("e", "DataFrameAddColumnByExpression", "output", PortStatus.RESOLVED, (passed, score)),)
    )


def _use_case(*, with_lineage: bool = True, node_ids=("e", "lonely")):
    projections = InMemoryProjectionRepository()
    if with_lineage:
        projections.lineage = {"p1": _lineage()}
    annotations = InMemoryAnnotationRepository()
    freshness = FakeFreshness()
    ids = iter(f"a{i}" for i in range(1, 100))
    use_case = SetNodeColumnDescriptions(
        annotations=annotations,
        graph_gateway=FakeGraphGateway(None, node_ids=node_ids),
        projections=projections,
        freshness=freshness,
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )
    return use_case, annotations, freshness


@pytest.mark.asyncio
async def test_upsert_takes_default_port_and_origin_from_lineage():
    use_case, annotations, freshness = _use_case()

    result = await use_case.execute(
        project_id="p1", organization_id="org", node_id="e", actor_user_id="u1",
        changes=[
            ColumnDescriptionChange("score", "  Скоринг клиента  "),
            ColumnDescriptionChange("customer_id", "Идентификатор клиента"),
            ColumnDescriptionChange("brand_new", "Колонки ещё нет в lineage"),
        ],
    )

    assert freshness.calls == [(("p1",), "org")]
    assert result.port == "output" and result.removed_columns == ()
    by_column = {item.column: item for item in annotations.items.values()}
    assert by_column["score"].description == "Скоринг клиента", "text is normalized"
    assert by_column["score"].origin_key == "node:e:output:score"
    assert by_column["customer_id"].origin_key == "ds:d1:f-id"
    assert by_column["brand_new"].origin_key is None
    assert all(item.description_updated_by == "u1" and item.updated_at == NOW for item in by_column.values())
    assert all(item.project_id == "p1" and item.node_id == "e" and item.port == "output" for item in by_column.values())


@pytest.mark.asyncio
async def test_update_keeps_identity_and_empty_text_removes_the_row():
    use_case, annotations, _ = _use_case()
    annotations.items["old"] = NodeColumnAnnotation(
        id="old", project_id="p1", node_id="e", port="output", column="score", description="Было",
        created_at=NOW, updated_at=NOW, description_updated_by="someone",
    )
    annotations.items["other"] = NodeColumnAnnotation(
        id="other", project_id="p1", node_id="e", port="output", column="customer_id", description="Клиент",
        created_at=NOW, updated_at=NOW,
    )

    result = await use_case.execute(
        project_id="p1", organization_id="org", node_id="e", actor_user_id="u2",
        changes=[ColumnDescriptionChange("score", "Стало"), ColumnDescriptionChange("customer_id", "   ")],
    )

    assert set(annotations.items) == {"old"}, "the identity of an edited annotation is preserved"
    assert annotations.items["old"].description == "Стало"
    assert annotations.items["old"].description_updated_by == "u2"
    assert result.removed_columns == ("customer_id",)
    assert [item.column for item in result.annotations] == ["score"]


@pytest.mark.asyncio
async def test_explicit_port_and_node_without_lineage_fall_back_to_output():
    use_case, annotations, _ = _use_case()

    explicit = await use_case.execute(
        project_id="p1", organization_id="org", node_id="e", port="df_left", actor_user_id="u1",
        changes=[ColumnDescriptionChange("score", "На другом порту")],
    )
    assert explicit.port == "df_left"
    assert next(iter(annotations.items.values())).origin_key is None, "lineage knows nothing about this port"

    lonely = await use_case.execute(
        project_id="p1", organization_id="org", node_id="lonely", actor_user_id="u1",
        changes=[ColumnDescriptionChange("x", "Нода без DataFrame-портов в lineage")],
    )
    assert lonely.port == "output"


@pytest.mark.asyncio
async def test_unknown_node_is_rejected_before_any_write():
    use_case, annotations, _ = _use_case()

    with pytest.raises(LineageNodePortNotFoundError):
        await use_case.execute(
            project_id="p1", organization_id="org", node_id="ghost", actor_user_id="u1",
            changes=[ColumnDescriptionChange("score", "x")],
        )
    assert annotations.items == {}


@pytest.mark.asyncio
async def test_project_without_lineage_still_accepts_descriptions():
    use_case, annotations, _ = _use_case(with_lineage=False)

    result = await use_case.execute(
        project_id="p1", organization_id="org", node_id="e", actor_user_id="u1",
        changes=[ColumnDescriptionChange("score", "Описание до первой проекции")],
    )

    assert result.port == "output"
    assert next(iter(annotations.items.values())).origin_key is None

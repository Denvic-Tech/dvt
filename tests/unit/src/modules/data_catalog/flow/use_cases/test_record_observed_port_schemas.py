from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    ObservedField,
    ObservedPortSchema,
    ProjectGraphSnapshot,
    ProjectStampSource,
)
from src.modules.data_catalog.flow import RecordObservedPortSchemas

from ..fakes import (
    FakeGraphGateway,
    InMemoryPortObservationRepository,
    InMemoryProjectionRepository,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def _observation(port: str, *names: str) -> ObservedPortSchema:
    return ObservedPortSchema(
        "p1", "x", port, tuple(ObservedField(name, "INT", True, i) for i, name in enumerate(names, 1)), NOW, task_id="t1"
    )


def _use_case():
    observations = InMemoryPortObservationRepository()
    projections = InMemoryProjectionRepository()
    graph = FakeGraphGateway(ProjectGraphSnapshot(stamp_source=ProjectStampSource("p1", "org", 7), nodes=(), edges=()))
    return RecordObservedPortSchemas(observations=observations, projections=projections, graph_gateway=graph), observations, projections


@pytest.mark.asyncio
async def test_first_observation_is_stored_with_the_project_revision_and_marks_the_projection_stale():
    use_case, observations, projections = _use_case()

    count = await use_case.execute([_observation("output", "a", "b"), _observation("inverted_output", "a")])

    assert count == 2
    stored = observations.items[("p1", "x", "output")]
    assert (stored.names, stored.graph_revision, stored.task_id) == (("a", "b"), 7, "t1")
    assert projections.stale_projects == ["p1"]


@pytest.mark.asyncio
async def test_unchanged_observation_does_not_touch_the_projection_but_a_changed_one_does():
    use_case, observations, projections = _use_case()
    await use_case.execute([_observation("output", "a", "b")])

    await use_case.execute([_observation("output", "a", "b")])
    assert projections.stale_projects == ["p1"], "same column names: nothing to rebuild"

    await use_case.execute([_observation("output", "a", "b", "c")])
    assert projections.stale_projects == ["p1", "p1"]
    assert observations.items[("p1", "x", "output")].names == ("a", "b", "c")

    assert await use_case.execute([]) == 0

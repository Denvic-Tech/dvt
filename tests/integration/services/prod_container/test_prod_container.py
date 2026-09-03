import pytest
from testcontainers.core.container import DockerContainer

pytestmark = pytest.mark.docker_required


DOCKER_FIXTURES = [
    "orchestrator_container",
    "task_worker_container",
    "gateway_container",
    "project_scheduler_container",
]

FIXTURE_TO_SERVICE = {
    "orchestrator_container": "orchestrator",
    "task_worker_container": "task-worker",
    "gateway_container": "gateway",
    "project_scheduler_container": "project-scheduler",
}


@pytest.mark.parametrize("fixture_name", DOCKER_FIXTURES)
def test_prod_containers_start(
    fixture_name: str,
    request: pytest.FixtureRequest,
    integration_test_settings,
) -> None:
    container = request.getfixturevalue(fixture_name)
    assert isinstance(container, DockerContainer)
    assert container.get_container_host_ip() is not None
    assert container.image == integration_test_settings.dvt_image(FIXTURE_TO_SERVICE[fixture_name])

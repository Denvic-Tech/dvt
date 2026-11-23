import hashlib
from types import SimpleNamespace
from uuid import uuid4

from services.installation_manager.domain.release_manifest import canonical_json
from services.installation_manager.host_bootstrap import container_name
from services.installation_manager.infrastructure import maintenance_host


def test_only_executor_from_same_update_route_can_share_the_data_mount(tmp_path, monkeypatch):
    instance = uuid4()
    root, prior_step, current_step, unrelated, planned_step = (uuid4() for _ in range(5))
    config = {"data": str(tmp_path), "instance": str(instance), "executor": "executor-reference"}
    host = maintenance_host.ComposeMaintenanceHost(config, current_step, {})
    route_roots = {prior_step: root, current_step: root, planned_step: root}
    store = SimpleNamespace(
        route_root=lambda step: route_roots.get(step, step),
        get=lambda step: {} if step in {root, prior_step, current_step, unrelated} else None,
    )
    monkeypatch.setattr(maintenance_host.OperationStore, "for_host", lambda _: store)
    monkeypatch.setattr(maintenance_host, "check_image", lambda _: "pinned-image-id")

    def runner(operation_id, *, name=None, image="pinned-image-id"):
        return {
            "Name": "/" + (name or container_name(config)),
            "Image": image,
            "Config": {
                "Labels": {
                    "dvt.executor.instance": str(instance),
                    "dvt.executor.operation": str(operation_id),
                }
            },
        }

    assert host._is_route_executor(runner(root))
    assert host._is_route_executor(runner(prior_step))
    assert host._is_route_executor(runner(current_step))
    assert not host._is_route_executor(runner(unrelated))
    assert not host._is_route_executor(runner(planned_step))
    assert not host._is_route_executor(runner("invalid"))
    assert not host._is_route_executor(runner(root, name="other"))
    assert not host._is_route_executor(runner(root, image="other"))


def test_legacy_supervisor_is_recognized_only_for_its_own_import_route(tmp_path, monkeypatch):
    instance, root, current_step = uuid4(), uuid4(), uuid4()
    config = {
        "data": str(tmp_path),
        "instance": str(instance),
        "project": "dvt",
        "executor": "executor-reference",
    }
    host = maintenance_host.ComposeMaintenanceHost(config, current_step, {})
    store = SimpleNamespace(
        route_root=lambda _: root,
        artifact_path=lambda *_: tmp_path,
    )
    monkeypatch.setattr(maintenance_host.OperationStore, "for_host", lambda _: store)
    monkeypatch.setattr(maintenance_host, "check_image", lambda _: "pinned-image-id")

    job_id = str(root)
    (tmp_path / "legacy-import.json").write_bytes(canonical_json({"legacy_job_id": job_id}))
    suffix = hashlib.sha256(f"dvt/{job_id}".encode()).hexdigest()[:24]
    container = {
        "Name": f"/dvt-legacy-handoff-{suffix}",
        "Image": "pinned-image-id",
        "HostConfig": {"NetworkMode": "host"},
        "Config": {"Labels": {"tech.denvic.legacy-bridge.handoff": suffix}},
    }
    assert host._is_legacy_supervisor(container)
    assert not host._is_legacy_supervisor({**container, "Image": "different-image"})
    assert not host._is_legacy_supervisor({**container, "HostConfig": {"NetworkMode": "dvt-net"}})
    (tmp_path / "legacy-import.json").write_bytes(canonical_json({"legacy_job_id": str(uuid4())}))
    assert not host._is_legacy_supervisor(container)

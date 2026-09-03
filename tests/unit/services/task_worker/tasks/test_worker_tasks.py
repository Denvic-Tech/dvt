import asyncio
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

from services.task_worker.tasks import worker_tasks

from src import enums
from src.modules.task_execution.domain.types import TaskTerminationReason
from src.pipeline.execution_mode import PipelineExecutionMode


class _UseCase:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class _Cancellation:
    def __init__(self, *, current_reason=None, wait_reason=None):
        self.current_reason = current_reason
        self.wait_reason = wait_reason
        self.wait_calls = []
        self.get_calls = []

    async def get_stop_reason(self, *, task_id):
        self.get_calls.append(task_id)
        return self.current_reason

    async def wait_for_stop(self, *, task_id):
        self.wait_calls.append(task_id)
        if self.wait_reason is None:
            await asyncio.Event().wait()
        return self.wait_reason


class _Processor:
    def __init__(self, result=None, error=None):
        self.result = result or SimpleNamespace(success=True, error_message=None)
        self.error = error
        self.nodes_outputs = {"n": {"out": object()}}
        self.nodes_output_hashes = {"n": {}}
        self.nodes_metadata = {"n": {}}
        self.node_signal_states = {"n": {}}
        self.executed_nodes = ["n"]
        self.failed_nodes = []
        self.skipped_nodes = []
        self.restored_nodes = []
        self._completed_node_ids = {"n"}
        self._recoverable_failed_node_ids = set()
        self._execution_order = ["n"]
        self._planned_execution_order = ["n"]
        self._affected_metadata_nodes = {"n"}
        self.pipeline = {"n": object()}
        self.task = object()
        self.stop_event = object()

    async def process(self):
        if self.error is not None:
            raise self.error
        return self.result


def _task(mode=PipelineExecutionMode.METADATA_ONLY, *, changed_node_ids=None, graph_revision=None):
    return SimpleNamespace(
        user_id="u1",
        task_id="t1",
        project_id="p1",
        send_ws_messages=False,
        mode=mode,
        changed_node_ids=changed_node_ids,
        graph_revision=graph_revision,
    )


def _install_common(monkeypatch, *, facade, task=None, processor=None):
    task = task or _task()
    processor = processor or _Processor()
    monkeypatch.setattr(worker_tasks, "build_task_execution_facade", lambda **_kwargs: facade)
    monkeypatch.setattr(worker_tasks, "_coerce_task", lambda _payload: task)
    monkeypatch.setattr(
        worker_tasks,
        "ensure_extension_runtime_for_task_process",
        lambda _required=None: None,
    )
    monkeypatch.setattr(worker_tasks, "ensure_log_sinks_for_task_process", lambda: None)
    monkeypatch.setattr(worker_tasks, "finalize_task_process_logging", lambda: None)
    monkeypatch.setattr(worker_tasks, "cleanup_tmp_partd_artifacts", lambda: None)
    monkeypatch.setattr(
        worker_tasks.app_settings_helpers,
        "get_app_settings",
        lambda: _async_value(SimpleNamespace(runtime=SimpleNamespace())),
    )
    monkeypatch.setattr(
        worker_tasks.ExecutionSettings,
        "from_app_runtime_settings",
        lambda _runtime: object(),
    )
    monkeypatch.setattr(worker_tasks, "run_task_telemetry_loop", _forever)
    monkeypatch.setattr(worker_tasks, "get_pipeline_processor", lambda **_kwargs: processor)
    monkeypatch.setattr(worker_tasks, "on_task_success", AsyncMock())
    monkeypatch.setattr(worker_tasks, "on_task_error", AsyncMock())
    monkeypatch.setattr(worker_tasks, "on_task_canceled", AsyncMock())
    return processor


def _facade(*, claim=True, running=True, finalize=True, cancellation=None):
    return SimpleNamespace(
        claim_task=_UseCase(claim),
        mark_task_running=_UseCase(running),
        finalize_task=_UseCase(finalize),
        cancellation=cancellation or _Cancellation(),
    )


def test_handle_task_claims_runs_and_finalizes_success(monkeypatch):
    facade = _facade()
    _install_common(monkeypatch, facade=facade)

    worker_tasks.handle_task({})

    assert facade.claim_task.calls == [{"task_id": "t1", "worker_id": worker_tasks.get_worker_id()}]
    assert facade.mark_task_running.calls == [{"task_id": "t1", "worker_id": worker_tasks.get_worker_id()}]
    assert facade.finalize_task.calls == [
        {"task_id": "t1", "worker_id": worker_tasks.get_worker_id(), "status": "SUCCESS"}
    ]
    worker_tasks.on_task_success.assert_awaited_once()


def test_duplicate_delivery_skips_pipeline_after_rejected_claim(monkeypatch):
    facade = _facade(claim=False)
    monkeypatch.setattr(
        worker_tasks,
        "get_pipeline_processor",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline must not start")),
    )
    _install_common(monkeypatch, facade=facade)
    monkeypatch.setattr(
        worker_tasks,
        "get_pipeline_processor",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("pipeline must not start")),
    )

    worker_tasks.handle_task({})

    assert len(facade.claim_task.calls) == 1
    assert facade.mark_task_running.calls == []
    assert facade.finalize_task.calls == []


def test_processor_unsuccessful_finalizes_error(monkeypatch):
    facade = _facade()
    processor = _Processor(SimpleNamespace(success=False, error_message="node failed"))
    _install_common(monkeypatch, facade=facade, processor=processor)

    worker_tasks.handle_task({})

    assert facade.finalize_task.calls[-1]["status"] == "ERROR"
    assert facade.finalize_task.calls[-1]["message"] == "node failed"
    worker_tasks.on_task_error.assert_awaited_once()


def test_processor_exception_finalizes_error(monkeypatch):
    facade = _facade()
    processor = _Processor(error=RuntimeError("boom"))
    _install_common(monkeypatch, facade=facade, processor=processor)

    worker_tasks.handle_task({})

    assert facade.finalize_task.calls[-1]["status"] == "ERROR"
    assert facade.finalize_task.calls[-1]["message"] == "boom"


def test_stop_during_task_finalizes_cancelled(monkeypatch):
    cancellation = _Cancellation(current_reason=TaskTerminationReason.USER_STOP.value)
    facade = _facade(cancellation=cancellation)
    _install_common(monkeypatch, facade=facade)

    worker_tasks.handle_task({})

    assert facade.finalize_task.calls[-1] == {
        "task_id": "t1",
        "worker_id": worker_tasks.get_worker_id(),
        "status": "CANCELLED",
        "termination_reason": TaskTerminationReason.USER_STOP.value,
    }
    worker_tasks.on_task_canceled.assert_awaited_once()


def test_oom_cancellation_reason_finalizes_error_not_cancelled(monkeypatch):
    cancellation = _Cancellation(current_reason=TaskTerminationReason.OOM_GUARD.value)
    facade = _facade(cancellation=cancellation)
    _install_common(monkeypatch, facade=facade)

    worker_tasks.handle_task({})

    assert facade.finalize_task.calls[-1] == {
        "task_id": "t1",
        "worker_id": worker_tasks.get_worker_id(),
        "status": "ERROR",
        "message": "Task terminated: OOM_GUARD",
    }
    worker_tasks.on_task_error.assert_awaited_once()
    worker_tasks.on_task_canceled.assert_not_awaited()


def test_success_finalize_race_with_stop_becomes_cancelled(monkeypatch):
    cancellation = _Cancellation()
    finalize = _UseCase(False)
    facade = _facade(cancellation=cancellation)
    facade.finalize_task = finalize
    _install_common(monkeypatch, facade=facade)

    calls = 0

    async def get_stop_reason(*, task_id):
        nonlocal calls
        calls += 1
        return None if calls == 1 else TaskTerminationReason.USER_STOP.value

    cancellation.get_stop_reason = get_stop_reason

    async def finalize_execute(**kwargs):
        if kwargs["status"] == "SUCCESS":
            return False
        finalize.calls.append(kwargs)
        return True

    finalize.execute = finalize_execute

    worker_tasks.handle_task({})

    assert any(call["status"] == "CANCELLED" for call in finalize.calls)
    worker_tasks.on_task_canceled.assert_awaited_once()


def test_graph_dirty_cleanup_only_after_success(monkeypatch):
    facade = _facade()
    task = _task(
        mode=PipelineExecutionMode.FULL,
        changed_node_ids=["node-1"],
        graph_revision=7,
    )
    clear = AsyncMock()
    monkeypatch.setattr(worker_tasks.project_crud, "clear_project_graph_dirty_if_revision", clear)

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return False
        async def commit(self): return None

    monkeypatch.setattr(worker_tasks, "AsyncSessionLocal", lambda: _Session())
    _install_common(monkeypatch, facade=facade, task=task)

    worker_tasks.handle_task({})

    clear.assert_awaited_once_with(
        ANY,
        project_id="p1",
        graph_revision=7,
        node_ids=["node-1"],
    )


def test_cleanup_releases_processor_references_on_success(monkeypatch):
    facade = _facade()
    processor = _install_common(monkeypatch, facade=facade)

    worker_tasks.handle_task({})

    assert processor.pipeline == {}
    assert processor.task is None
    assert processor.nodes_outputs == {}


async def _async_value(value):
    return value


async def _forever(*_args, **_kwargs):
    await asyncio.Event().wait()

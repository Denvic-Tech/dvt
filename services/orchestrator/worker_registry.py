import asyncio

from services.orchestrator.worker_state import WorkerState

from src.enums import WorkerStatus
from src.logger import logger
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.system import SystemInfo

import config


class WorkerRegistry:
    """
    In-memory реестр воркеров и их текущего состояния.

    Хранит последние heartbeat, доступные режимы выполнения и системные метрики.
    """

    def __init__(self):
        """Создаёт пустой реестр воркеров."""
        self._workers: dict[str, WorkerState] = {}
        self._lock = asyncio.Lock()
        self._log = logger.bind(component="WorkerRegistry")

    def all(self) -> list[WorkerState]:
        """Возвращает список всех известных воркеров (включая dead/offline)."""
        return list(self._workers.values())

    def get(self, worker_id: str) -> WorkerState | None:
        """Возвращает состояние воркера по идентификатору или None, если воркер не известен."""
        return self._workers.get(worker_id)

    def mark_busy(self, *, worker_id: str, task_id: str) -> None:
        worker = self._workers.get(worker_id)
        if worker is None:
            return
        worker.active_task_id = task_id
        worker.is_busy = True
        worker.available_slots = 0

    def mark_idle(self, *, worker_id: str, task_id: str | None = None) -> None:
        worker = self._workers.get(worker_id)
        if worker is None:
            return
        if task_id is not None and worker.active_task_id not in (None, task_id):
            return
        worker.active_task_id = None
        worker.is_busy = False
        worker.available_slots = (
            max(int(worker.max_concurrent), 0)
            if worker.status == WorkerStatus.ONLINE
            else 0
        )

    def get_alive_workers(self, now_ts: float) -> list[WorkerState]:
        """
        Возвращает список живых воркеров на момент времени now_ts.

        Живыми считаются воркеры, чьи heartbeat не старше заданного timeout.
        """
        return [
            w for w in self._workers.values()
            if w.is_alive(now_ts, config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC)
        ]

    # --- heartbeat update ---

    async def update_from_heartbeat(
            self,
            *,
            worker_id: str,
            capabilities: set[PipelineExecutionMode],
            max_concurrent: int,
            timestamp: float,
            received_at: float,
            active_task_id: str | None = None,
            is_busy: bool | None = None,
            available_slots: int | None = None,
            system_info: SystemInfo | None = None,
    ) -> WorkerState:
        """
        Обновляет (или создаёт) состояние воркера из heartbeat-сообщения.

        Всегда устанавливает статус "online", обновляет способности и system_info.
        Возвращает актуальный объект WorkerState.
        """

        async with self._lock:
            worker_state = self._workers.get(worker_id)
            previous_status = worker_state.status if worker_state is not None else None
            previous_last_received_at = worker_state.last_received_at if worker_state is not None else None
            previous_offline_since = worker_state.offline_since if worker_state is not None else None

            worker_status = WorkerStatus.ONLINE

            availability_reported = is_busy is not None or available_slots is not None
            heartbeat_busy = bool(is_busy) if is_busy is not None else False
            heartbeat_available_slots = (
                max(int(available_slots), 0)
                if available_slots is not None
                else (0 if heartbeat_busy else max(int(max_concurrent), 0))
            )

            if worker_state is None:
                worker_state = WorkerState(
                    worker_id=worker_id,
                    timestamp=timestamp,
                    first_seen_at=received_at,
                    last_received_at=received_at,
                    last_status_change_at=received_at,
                    capabilities=capabilities,
                    max_concurrent=max_concurrent,
                    status=worker_status,
                    active_task_id=active_task_id if availability_reported else None,
                    is_busy=heartbeat_busy if availability_reported else False,
                    available_slots=(
                        heartbeat_available_slots
                        if availability_reported and worker_status == WorkerStatus.ONLINE
                        else max(int(max_concurrent), 0)
                    ),
                    availability_reported=availability_reported,
                    system_info=system_info,
                )
            else:
                worker_state.timestamp = timestamp
                worker_state.last_received_at = received_at
                worker_state.capabilities = capabilities
                worker_state.max_concurrent = max_concurrent
                worker_state.status = worker_status
                if availability_reported:
                    worker_state.active_task_id = active_task_id
                    worker_state.is_busy = heartbeat_busy
                    worker_state.available_slots = (
                        heartbeat_available_slots
                        if worker_status == WorkerStatus.ONLINE
                        else 0
                    )
                    worker_state.availability_reported = True
                else:
                    worker_state.available_slots = (
                        0 if worker_state.is_busy else max(int(max_concurrent), 0)
                    )
                worker_state.system_info = system_info
                if previous_status != worker_status:
                    worker_state.last_status_change_at = received_at

            if worker_status == WorkerStatus.ONLINE:
                worker_state.offline_since = None

            self._workers[worker_id] = worker_state

            hostname = system_info.hostname if system_info is not None else None
            heartbeat_transport_delay_sec = max(float(received_at) - float(timestamp), 0.0)

            if previous_status is None:
                self._log.info(
                    "Registered worker from heartbeat",
                    worker_id=worker_id,
                    hostname=hostname,
                    max_concurrent=max_concurrent,
                    capabilities=sorted(str(capability) for capability in capabilities),
                    heartbeat_transport_delay_sec=heartbeat_transport_delay_sec,
                )
            elif previous_status == WorkerStatus.OFFLINE and worker_status == WorkerStatus.ONLINE:
                offline_duration_sec = (
                    max(float(received_at) - float(previous_offline_since), 0.0)
                    if previous_offline_since is not None
                    else None
                )
                self._log.info(
                    "Worker heartbeat restored",
                    worker_id=worker_id,
                    hostname=hostname,
                    heartbeat_transport_delay_sec=heartbeat_transport_delay_sec,
                    heartbeat_gap_sec=(
                        max(float(received_at) - float(previous_last_received_at), 0.0)
                        if previous_last_received_at is not None
                        else None
                    ),
                    offline_duration_sec=offline_duration_sec,
                )
            elif previous_status != worker_status:
                self._log.info(
                    "Worker status changed from heartbeat update",
                    worker_id=worker_id,
                    hostname=hostname,
                    previous_status=str(previous_status) if previous_status is not None else None,
                    new_status=str(worker_status),
                    heartbeat_transport_delay_sec=heartbeat_transport_delay_sec,
                )

            return worker_state

    # --- GC dead workers ---

    def reap_dead_workers(self, now_ts: float) -> list[WorkerState]:
        """
        Помечает воркеров как dead, если их heartbeat устарел, и возвращает их состояния.

        Используется планировщиком для логирования и последующей обработки.
        """
        dead_workers: list[WorkerState] = []
        for worker_id, state in self._workers.items():
            if not state.is_alive(
                    now_ts,
                    config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC,
            ) and state.status != WorkerStatus.OFFLINE:
                state.status = WorkerStatus.OFFLINE
                state.active_task_id = None
                state.is_busy = False
                state.available_slots = 0
                state.offline_since = now_ts
                state.last_status_change_at = now_ts
                dead_workers.append(state)
                self._log.warning(
                    "Worker marked offline due to stale heartbeat",
                    worker_id=worker_id,
                    hostname=state.system_info.hostname if state.system_info is not None else None,
                    heartbeat_timeout_sec=config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC,
                    last_heartbeat_at=state.timestamp,
                    last_heartbeat_received_at=state.last_received_at,
                    heartbeat_age_sec=max(float(now_ts) - float(state.last_received_at), 0.0),
                    first_seen_at=state.first_seen_at,
                )
        return dead_workers

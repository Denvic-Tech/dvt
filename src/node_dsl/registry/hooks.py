import asyncio
import inspect
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from src.node_dsl.hooks import HookEntry, HookStage
from src.pipeline.execution_mode import PipelineExecutionMode

from ._bootstrap import ensure_bootstrapped, registry_transaction, reset_bootstrap_state

if TYPE_CHECKING:
    from src.node_dsl.base_node.base import BaseNode


HOOKS_REGISTRY: dict[str, dict[HookStage, list[HookEntry]]] = defaultdict(lambda: defaultdict(list))

_REGISTRY_LOCK = threading.RLock()


def build(node_cls: type["BaseNode"]) -> None:
    node_name = node_cls.__name__
    node_hook_entries: list[HookEntry] = []
    _decl_order = 0

    for attr_name, attr_value in inspect.getmembers(node_cls, inspect.isfunction):
        if callable(attr_value) and hasattr(attr_value, "__node_hooks__"):
            for spec in getattr(attr_value, "__node_hooks__"):
                hook_entry = HookEntry(method_name=attr_name, spec=spec, order=_decl_order)
                node_hook_entries.append(hook_entry)
                _decl_order += 1

    combined_registry: dict[HookStage, list[HookEntry]] = defaultdict(list)

    with registry_transaction(), _REGISTRY_LOCK:
        for base_node in node_cls.__bases__:
            base_node_hooks = HOOKS_REGISTRY.get(base_node.__name__, {})
            for stage, entries in base_node_hooks.items():
                combined_registry[stage].extend(entries)

        for entry in node_hook_entries:
            combined_registry[entry.spec.stage].append(entry)

        for stage, entries in combined_registry.items():
            dedup: dict[str, HookEntry] = {}
            for e in entries:
                dedup[e.method_name] = e  # последнее (из наследника) победит
            sorted_entries = sorted(dedup.values(), key=lambda x: (-x.spec.priority, x.order))
            combined_registry[stage] = sorted_entries

        HOOKS_REGISTRY[node_name] = dict(combined_registry)


def add(node_cls: type["BaseNode"], hook_entry: "HookEntry") -> None:
    node_name = node_cls.__name__

    with registry_transaction(), _REGISTRY_LOCK:
        if hook_entry in HOOKS_REGISTRY[node_name][hook_entry.spec.stage]:
            raise ValueError(
                f"Hook '{hook_entry.method_name}' for node '{node_name}' "
                f"at stage '{hook_entry.spec.stage}' is already registered."
            )

        HOOKS_REGISTRY[node_name][hook_entry.spec.stage].append(hook_entry)
        HOOKS_REGISTRY[node_name][hook_entry.spec.stage].sort(
            key=lambda entry: (-entry.spec.priority, entry.order)
        )


def _snapshot(node_cls: type["BaseNode"]) -> dict[HookStage, list[HookEntry]]:
    """Безопасно читаем срез для класса ноды, чтобы потом работать без блокировки."""
    node_name = node_cls.__name__
    with registry_transaction(), _REGISTRY_LOCK:
        node_hooks = HOOKS_REGISTRY.get(node_name)
        if not node_hooks:
            return {}
        # Глубокая «поверхностная» копия уровнем списков, чтобы избежать гонок при чтении
        return {stage: list(entries) for stage, entries in node_hooks.items()}


def get(
    node_cls: type["BaseNode"], stage: HookStage | None = None, exec_mode: PipelineExecutionMode | None = None
) -> list[tuple[Callable[..., Any], HookEntry]]:
    ensure_bootstrapped(is_ready=lambda: bool(HOOKS_REGISTRY))
    hooks_by_stage = _snapshot(node_cls)
    results: list[tuple[Callable[..., Any], HookEntry]] = []
    if not hooks_by_stage:
        return results

    for hook_stage, entries in hooks_by_stage.items():
        if stage is not None and hook_stage != stage:
            continue
        for entry in entries:
            if exec_mode is None or entry.spec.mode == exec_mode:
                # Берём «непривязанный» дескриптор (метод класса). Привяжем на вызове.
                bound = getattr(node_cls, entry.method_name)
                results.append((bound, entry))
    return results


async def run_async(
    node: "BaseNode",
    stage: HookStage | None = None,
    exec_mode: PipelineExecutionMode | None = None,
    *,
    concurrently: bool = True,
    return_exceptions: bool = False,
    max_concurrency: int | None = None,
) -> dict[str, Any]:
    """
    Запускает *хуки текущей стадии* для заданной ноды, безопасно для asyncio.

    - Async-методы: await напрямую.
    - Sync-методы: выполняются в thread-пуле через asyncio.to_thread(), чтобы не блокировать event loop.
    - Если sync-метод вернул awaitable (редкий кейс), результат дополнительно будет await-нут.
    - Порядок хуков внутри стадии — как вернул реестр (обычно уже отсортирован).
    - `concurrently=True` — гоняет хуки параллельно (можно ограничить `max_concurrency`).
    - Возвращает dict: {method_name: result_or_exception}.
      При `return_exceptions=False` исключения пробрасываются наружу:
        - в параллельном режиме `asyncio.gather` прерывает выполнение и поднимет исключение,
        - в последовательном — будет поднято при первом же fall.
    """

    # --- внутренний helper: корректно вызвать bound-метод (sync/async) ---
    async def _call_maybe(bound_fn):
        # Явная корутин-функция
        if inspect.iscoroutinefunction(bound_fn):
            return await bound_fn()

        # Не корутин-функция: уводим синхронный вызов в thread
        # (важно вызывать сам bound_fn в to_thread, чтобы не блокировать loop)
        res = await asyncio.to_thread(bound_fn)

        # На случай, если sync вернул awaitable (редко, но бывает)
        if inspect.isawaitable(res):
            return await res
        return res

    # --- собрать хуки стадии как (method_name, bound_fn) ---
    items: list[tuple[str, Any]] = []
    for fn, entry in get(type(node), stage, exec_mode):
        name = entry.method_name
        bound_fn = getattr(node, name)
        items.append((name, bound_fn))

    results: dict[str, Any] = {}

    if not items:
        return results

    # --- последовательный режим (жёсткий порядок и простой error handling) ---
    if not concurrently:
        for name, bound_fn in items:
            try:
                results[name] = await _call_maybe(bound_fn)
            except Exception as e:
                if return_exceptions:
                    results[name] = e
                else:
                    raise
        return results

    # --- параллельный режим ---
    # Опционально ограничим количество одновременных запусков
    sem = asyncio.Semaphore(max_concurrency) if (max_concurrency and max_concurrency > 0) else None

    async def _runner(name: str, bound_fn):
        if sem is None:
            return await _call_maybe(bound_fn)
        async with sem:
            return await _call_maybe(bound_fn)

    # Список корутин в исходном порядке (для детерминированной сборки результатов)
    coros = [_runner(name, bound_fn) for name, bound_fn in items]

    if return_exceptions:
        finished = await asyncio.gather(*coros, return_exceptions=True)
        for (name, _), value in zip(items, finished):
            results[name] = value
        return results

    # return_exceptions=False — исключение пробрасываем сразу
    finished = await asyncio.gather(*coros, return_exceptions=False)
    for (name, _), value in zip(items, finished):
        results[name] = value
    return results


@lru_cache(maxsize=1)
def _get_executor():
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="node-hooks-runner")


def run(
    node: "BaseNode",
    stage: HookStage | None = None,
    exec_mode: PipelineExecutionMode | None = None,
) -> dict[str, Any]:
    """
    Синхронная обёртка над run_async.
    Безопасна и вне, и внутри работающего event loop:
    - если цикла нет: создаём временный через asyncio.run(...)
    - если цикл уже работает в ТЕКУЩЕМ потоке: выполняем run_async в ОТДЕЛЬНОМ потоке со своим loop
      (во избежание deadlock'а)
    """
    try:
        loop = asyncio.get_running_loop()
        in_running_loop = loop.is_running()
    except RuntimeError:
        in_running_loop = False

    if not in_running_loop:
        # обычный sync-код: просто запускаем корутину
        return asyncio.run(
            run_async(
                node,
                stage=stage,
                exec_mode=exec_mode,
                # можешь тут выставить concurrently=True, если нужно
                concurrently=False,
            )
        )

    # Мы уже ВНУТРИ запущенного event loop в этом же потоке -> уйдём в отдельный поток
    executor = _get_executor()
    future = executor.submit(
        lambda: asyncio.run(
            run_async(
                node,
                stage=stage,
                exec_mode=exec_mode,
                # для консистентности с прежним поведением:
                concurrently=False,
            )
        )
    )
    return future.result()


def get_all(
    stage: HookStage | None = None, exec_mode: PipelineExecutionMode | None = None
) -> dict[str, list["HookEntry"]]:
    ensure_bootstrapped(is_ready=lambda: bool(HOOKS_REGISTRY))
    with registry_transaction(), _REGISTRY_LOCK:
        items = list(HOOKS_REGISTRY.items())

    result: dict[str, list[HookEntry]] = defaultdict(list)
    for node_name, hooks_by_stage in items:
        for hook_stage, entries in hooks_by_stage.items():
            if stage is None or hook_stage == stage:
                filtered_entries = [
                    entry for entry in entries if exec_mode is None or entry.spec.mode == exec_mode
                ]
                if filtered_entries:
                    result[node_name].extend(filtered_entries)
    return dict(result)


def clear() -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        HOOKS_REGISTRY.clear()
    reset_bootstrap_state()

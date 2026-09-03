from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from src.pipeline.execution_mode import PipelineExecutionMode
from src.types import MaybeAsyncFn

NodeMethod = MaybeAsyncFn[["BaseNode"], None]


class HookStage(StrEnum):
    BEFORE_PROCESS = "before_process"
    AFTER_PROCESS = "after_process"
    ON_VALIDATION = "on_validation"
    ON_ERROR = "on_error"


@dataclass(frozen=True)
class HookSpec:
    stage: HookStage
    mode: PipelineExecutionMode | None = None
    priority: int = 0
    name: str | None = None
    once: bool = False


@dataclass(frozen=True)
class HookEntry:
    method_name: str
    spec: HookSpec
    order: int


def _append_hook_attr(fn: Callable, spec: HookSpec) -> Callable:
    """Копим список спеков на самом методе (поддержка нескольких декораторов/хуков на один метод)."""
    lst: list[HookSpec] = getattr(fn, "__node_hooks__", [])
    lst.append(spec)
    setattr(fn, "__node_hooks__", lst)
    return fn


def before_process(
        fn: NodeMethod | None = None,
        /,
        *,
        mode: PipelineExecutionMode | None = None,
        priority: int = 0,
        name: str | None = None,
        once: bool = False
):
    def deco(inner: NodeMethod) -> Callable:
        spec = HookSpec(stage=HookStage.BEFORE_PROCESS,
                        mode=mode, priority=priority, name=name, once=once)
        return _append_hook_attr(inner, spec)

    if fn is not None:
        return deco(fn)

    return deco


def after_process(
        fn: NodeMethod | None = None,
        /,
        *,
        mode: str | PipelineExecutionMode | None = None,
        priority: int = 0,
        name: str | None = None,
        once: bool = False
):
    def deco(inner: NodeMethod) -> Callable:
        spec = HookSpec(stage=HookStage.AFTER_PROCESS,
                        mode=mode, priority=priority, name=name, once=once)
        return _append_hook_attr(inner, spec)

    if fn is not None:
        return deco(fn)

    return deco


def on_validation(
        fn: NodeMethod | None = None,
        /,
        *,
        priority: int = 0,
        name: str | None = None,
        once: bool = False
):
    def deco(inner: NodeMethod) -> Callable:
        spec = HookSpec(stage=HookStage.ON_VALIDATION,
                        priority=priority, name=name, once=once)
        return _append_hook_attr(inner, spec)

    if fn is not None:
        return deco(fn)

    return deco

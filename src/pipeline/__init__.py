"""Public DVT pipeline API."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .processor import PipelineProcessor

__all__ = ["PipelineProcessor"]


def __getattr__(name: str) -> Any:
    if name != "PipelineProcessor":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = import_module("src.pipeline.processor").PipelineProcessor
    globals()[name] = value
    return value

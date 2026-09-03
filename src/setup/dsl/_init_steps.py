from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterable, Type

from . import registry as setup_registry
from .base import BaseSetupStep


def _import_step_modules(steps_dir: Path) -> None:
    for path in steps_dir.rglob("*.py"):
        if path.name.startswith("_"):
            continue

        relative_path = path.relative_to(steps_dir)
        module_name = "src.setup.steps." + relative_path.with_suffix("").as_posix().replace("/", ".")
        importlib.import_module(module_name)


def _iter_step_subclasses(base_cls: Type[BaseSetupStep]) -> Iterable[Type[BaseSetupStep]]:
    for child_cls in base_cls.__subclasses__():
        yield child_cls
        yield from _iter_step_subclasses(child_cls)


def init_setup_steps(*, force: bool = False) -> None:
    if setup_registry.is_initialized() and not force:
        return

    if force:
        setup_registry.clear()

    steps_dir = Path(__file__).resolve().parents[1] / "steps"
    _import_step_modules(steps_dir)

    step_classes = [
        step_cls
        for step_cls in _iter_step_subclasses(BaseSetupStep)
        if step_cls.__module__.startswith("src.setup.steps.")
    ]
    unique_step_classes = list(dict.fromkeys(step_classes))

    if not unique_step_classes:
        raise RuntimeError("No setup step classes were found for registration.")

    for step_cls in sorted(unique_step_classes, key=lambda cls: cls.sort_key()):
        setup_registry.add(step_cls)

    setup_registry.mark_initialized(True)

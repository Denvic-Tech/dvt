import multiprocessing as mp
import sys
from typing import Optional


def get_context_by_platform(prefer: Optional[str] = None) -> mp.context.BaseContext:
    """
    Возвращает multiprocessing context в зависимости от платформы.

    Args:
        prefer: Предпочитаемый метод запуска ('fork', 'spawn', 'forkserver').

    Returns:
        multiprocessing context.
    """

    available = mp.get_all_start_methods()

    # Если явно указан prefer и он доступен
    if prefer and prefer in available:
        return mp.get_context(prefer)

    # Windows → только spawn
    if sys.platform.startswith("win"):
        return mp.get_context("spawn")

    # Unix-like
    if "fork" in available:
        return mp.get_context("fork")

    if "forkserver" in available:
        return mp.get_context("forkserver")

    raise ValueError("Нет доступного метода запуска для multiprocessing. Доступные методы: {}".format(available))

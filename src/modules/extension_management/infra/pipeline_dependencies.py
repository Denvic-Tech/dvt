"""Resolve pipeline extension dependencies through the node registry."""

from src.node_dsl.registry import definitions as definitions_registry
from src.pipeline.types import Pipeline


def collect_extension_names(pipeline: Pipeline) -> set[str]:
    """Собирает имена расширений, используемых в пайплайне.

    Args:
        pipeline: Словарь {node_id: NodeData} с узлами пайплайна.

    Returns:
        Множество имен расширений, которые используются в узлах пайплайна.
    """
    extension_names: set[str] = set()
    for node in pipeline.values():
        node_name = getattr(node, "name", None)
        if not node_name:
            continue
        try:
            node_def = definitions_registry.get(node_name)
        except Exception:
            continue
        if node_def.extension_name:
            extension_names.add(node_def.extension_name)
    return extension_names


import inspect
import re

from src.node_dsl.registry import definitions as definitions_registry, nodes as nodes_registry
from src.utils.repo_paths import normalize_repo_relative_path, repo_relative_path_to_module

_TRACEBACK_FILE_RE = re.compile(
    r'^\s*File "(?P<path>.+?)", line (?P<line>\d+), in (?P<function>.+)$',
    re.MULTILINE,
)


def extract_traceback_source_modules(traceback_text: str | None) -> list[str]:
    if not traceback_text:
        return []

    modules: list[str] = []
    for match in _TRACEBACK_FILE_RE.finditer(traceback_text):
        normalized_path = normalize_repo_relative_path(match.group("path"))
        if not normalized_path:
            continue

        module_name = repo_relative_path_to_module(normalized_path)
        if module_name and module_name not in modules:
            modules.append(module_name)

    return modules


def resolve_node_source(node_name: str) -> tuple[str, str | None]:
    python_module: str | None = None
    source_file: str | None = None

    try:
        node_definition = definitions_registry.get(node_name)
        python_module = node_definition.python_module
    except Exception:
        node_definition = None

    try:
        node_class = nodes_registry.get(node_name)
    except Exception:
        node_class = None
    else:
        python_module = python_module or getattr(node_class, "__module__", None)
        source_file = normalize_repo_relative_path(
            inspect.getsourcefile(node_class),
            allow_outside_root=True,
        )

    if python_module is None and node_definition is not None:
        python_module = getattr(node_definition, "python_module", None)

    return python_module or "unknown", source_file

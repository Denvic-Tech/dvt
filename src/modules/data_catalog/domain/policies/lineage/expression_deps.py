"""Статическое извлечение зависимостей pandas/Dask-выражения от колонок входа."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable

_BACKTICK = re.compile(r"`([^`]*)`")
_LOCAL_VAR = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")


def expression_dependencies(expression: str, columns: Iterable[str]) -> tuple[tuple[str, ...], bool]:
    """Колонки входа, на которые ссылается выражение, и флаг «разобрать не удалось».

    Имена в обратных кавычках и ссылки `@var` заменяются плейсхолдерами до `ast.parse`,
    чтобы синтаксис pandas.eval не ломал разбор. Возвращаются только имена, реально
    присутствующие во входе, в порядке их появления.
    """
    available = {name: name for name in columns}
    placeholders: dict[str, str] = {}

    def _quote(match: re.Match[str]) -> str:
        token = f"__dvt_bt_{len(placeholders)}__"
        placeholders[token] = match.group(1)
        return token

    prepared = _BACKTICK.sub(_quote, expression)
    prepared = _LOCAL_VAR.sub(lambda m: f"__dvt_local_{m.group(1)}__", prepared)

    try:
        tree = ast.parse(prepared.strip(), mode="eval")
    except SyntaxError:
        return (), True

    positioned: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        name = placeholders.get(node.id, node.id)
        if name.startswith("__dvt_local_") or name not in available:
            continue
        positioned.append((node.lineno, node.col_offset, name))
    found: list[str] = []
    for _, _, name in sorted(positioned):
        if name not in found:
            found.append(name)
    return tuple(found), False

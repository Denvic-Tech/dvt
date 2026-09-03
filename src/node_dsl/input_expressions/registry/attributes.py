from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AllowedAttributeRule:
    owner_type: type[Any]
    attributes: frozenset[str]


_ATTRIBUTE_RULES: dict[str, AllowedAttributeRule] = {}
_LOCK = threading.RLock()


def add(
        name: str,
        *,
        owner_type: type[Any],
        attributes: Iterable[str],
) -> None:
    with _LOCK:
        _ATTRIBUTE_RULES[name] = AllowedAttributeRule(
            owner_type=owner_type,
            attributes=frozenset(attributes),
        )


def get(name: str) -> AllowedAttributeRule:
    with _LOCK:
        try:
            return _ATTRIBUTE_RULES[name]
        except KeyError as err:
            raise KeyError(f"Allowed attribute rule '{name}' not found") from err


def is_allowed(
        rule_names: Iterable[str],
        *,
        obj: Any,
        attr: str,
) -> bool:
    with _LOCK:
        rules = tuple(get(name) for name in rule_names)

    return any(
        isinstance(obj, rule.owner_type) and attr in rule.attributes
        for rule in rules
    )

"""Тексты объяснений lineage из `locales/{lang}/lineage.json` с fallback на английский."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...domain import LineageTextRenderer

DEFAULT_LOCALE = "en"


class _SafeParams(dict):
    def __missing__(self, key: str) -> str:
        return "?"


@lru_cache(maxsize=16)
def _load_templates(path: str) -> dict[str, str]:
    file = Path(path)
    if not file.is_file():
        return {}
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if isinstance(value, str)}


class JsonLineageTemplateRenderer(LineageTextRenderer):
    def __init__(self, locales_dir: Path | str) -> None:
        self._locales_dir = Path(locales_dir)

    def render(self, template_key: str, params: Mapping[str, Any], locale: str) -> str | None:
        template = self._template(template_key, locale)
        if template is None and locale != DEFAULT_LOCALE:
            template = self._template(template_key, DEFAULT_LOCALE)
        if template is None:
            return None
        try:
            return template.format_map(_SafeParams({k: v for k, v in params.items() if k != "template"}))
        except (ValueError, IndexError):
            return template

    def _template(self, key: str, locale: str) -> str | None:
        safe_locale = "".join(ch for ch in locale.lower() if ch.isalnum() or ch in "-_") or DEFAULT_LOCALE
        return _load_templates(str(self._locales_dir / safe_locale / "lineage.json")).get(key)

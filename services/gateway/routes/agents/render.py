"""Rendering of the agent-facing connection instruction."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TEMPLATE_PATH = Path(__file__).with_name("connect_template.md")
_API_PREFIX = "/api"


def mcp_url(public_url: str) -> str:
    return f"{public_url}/mcp"


def connect_url(public_url: str, raw_code: str) -> str:
    return f"{public_url}{_API_PREFIX}/agents/connect/{raw_code}.md"


def claim_url(public_url: str, raw_code: str) -> str:
    return f"{public_url}{_API_PREFIX}/agents/claim/{raw_code}"


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def render_instruction(public_url: str, raw_code: str) -> str:
    return (
        _template()
        .replace("{{DVT_HOST}}", public_url.split("://", 1)[-1])
        .replace("{{DVT_URL}}", public_url)
        .replace("{{DVT_MCP_URL}}", mcp_url(public_url))
        .replace("{{CLAIM_URL}}", claim_url(public_url, raw_code))
    )


def invalid_link_markdown(reason: str) -> str:
    return (
        "# Ссылка подключения недействительна\n\n"
        f"{reason} Попросите пользователя создать новую ссылку в DVT "
        "(профиль → Подключить ИИ-агента) и остановитесь.\n"
    )

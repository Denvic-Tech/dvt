from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from services.gateway.deps import get_node_documentation_repository

from src.enums import ExtensionDepsStatus
from src.models.extension import ExtensionRecord
from src.modules.node_documentation.domain.exceptions import (
    NodeDocumentationNotFound,
    UnknownNode,
)
from src.modules.node_documentation.flow.use_cases import GetNodeDocumentation
from src.modules.node_documentation.infra import DSLNodeRegistry
from src.node_dsl import get_all_definitions, get_definition

from .access import get_accessible_project, list_accessible_projects
from .auth import MCPPrincipal
from .errors import AIMCPHTTPError
from .pagination import decode_cursor, encode_cursor

EXCLUDED_AI_MCP_NODES = frozenset({"GetExistKafkaConnection", "ReadQueueTopic"})


async def list_projects(
    *,
    session,
    principal: MCPPrincipal,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    offset = decode_cursor(cursor)
    projects = await list_accessible_projects(session, principal, search=search)
    page = projects[offset : offset + limit]
    return {
        "items": [
            {
                "id": project.id,
                "name": project.name,
                "folder_id": project.folder_id,
                "graph_revision": project.graph_revision,
                "updated_at": project.updated_at.isoformat(),
            }
            for project in page
        ],
        "next_cursor": encode_cursor(offset + len(page), len(projects)),
    }


async def get_project(*, session, principal: MCPPrincipal, project_id: str) -> dict[str, Any]:
    project = await get_accessible_project(session, principal, project_id)
    return {
        "id": project.id,
        "name": project.name,
        "folder_id": project.folder_id,
        "graph_revision": project.graph_revision,
        "variables": project.variables or {},
        "store_enabled": project.store_enabled,
        "updated_at": project.updated_at.isoformat(),
    }


async def _ready_extensions(session) -> set[str]:
    return set(
        (
            await session.execute(
                sa.select(ExtensionRecord.name).where(
                    ExtensionRecord.is_enabled.is_(True),
                    ExtensionRecord.is_installed.is_(True),
                    ExtensionRecord.deps_status == ExtensionDepsStatus.READY,
                )
            )
        )
        .scalars()
        .all()
    )


async def _available_definitions(session, locale: str) -> dict:
    ready_extensions = await _ready_extensions(session)
    return {
        name: definition
        for name, definition in get_all_definitions(lang=locale).items()
        if name not in EXCLUDED_AI_MCP_NODES
        and definition.visible
        and not definition.deprecated
        and (not definition.extension_name or definition.extension_name in ready_extensions)
    }


def _definition_field_types(fields: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for field in fields.values():
        values = field.type if isinstance(field.type, list) else [field.type]
        result.update(str(value) for value in values)
    return result


async def _node_documentation(node_name: str, locale: str) -> str:
    try:
        documentation = await GetNodeDocumentation(
            repository=get_node_documentation_repository(),
            registry=DSLNodeRegistry(),
        ).execute(node_name=node_name, locale=locale)
    except (NodeDocumentationNotFound, UnknownNode):
        return ""
    else:
        return documentation.content


async def search_nodes(
    *,
    session,
    principal: MCPPrincipal,
    query: str = "",
    category: str | None = None,
    tags: list[str] | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
    limit: int = 50,
    locale: str = "en",
) -> dict[str, Any]:
    _ = principal  # Authentication is enforced by the dispatcher; the catalog is instance-wide.
    definitions = await _available_definitions(session, locale)
    query_tokens = [token for token in query.lower().split() if token]
    required_tags = {tag.lower() for tag in tags or []}
    scored: list[tuple[int, str, Any]] = []
    for name, definition in definitions.items():
        if category and definition.category.lower() != category.lower():
            continue
        definition_tags = {tag.lower() for tag in definition.tags}
        if required_tags and not required_tags.issubset(definition_tags):
            continue
        input_types = {
            item.lower() for item in _definition_field_types(definition.input_definitions)
        }
        output_types = {
            item.lower() for item in _definition_field_types(definition.output_definitions)
        }
        if input_type and input_type.lower() not in input_types:
            continue
        if output_type and output_type.lower() not in output_types:
            continue
        documentation = await _node_documentation(name, locale) if query_tokens else ""
        haystack = " ".join(
            [
                name,
                definition.display_name,
                definition.description,
                definition.category,
                *definition.tags,
                documentation,
            ]
        ).lower()
        if query_tokens and not all(token in haystack for token in query_tokens):
            continue
        score = sum(10 if token in name.lower() else 1 for token in query_tokens)
        scored.append((-score, name.lower(), definition))
    scored.sort(key=lambda item: (item[0], item[1]))
    items = []
    for _, _, definition in scored[: max(1, min(limit, 200))]:
        items.append(
            {
                "name": definition.name,
                "display_name": definition.display_name,
                "description": definition.description,
                "category": definition.category,
                "tags": definition.tags,
                "type": str(definition.type),
                "input_types": sorted(_definition_field_types(definition.input_definitions)),
                "output_types": sorted(_definition_field_types(definition.output_definitions)),
                "extension_name": definition.extension_name,
            }
        )
    return {"items": items}


async def get_node_definition(
    *,
    session,
    principal: MCPPrincipal,
    node_name: str,
    locale: str = "en",
) -> dict[str, Any]:
    _ = principal  # Authentication is enforced by the dispatcher; the catalog is instance-wide.
    definitions = await _available_definitions(session, locale)
    if node_name not in definitions:
        raise AIMCPHTTPError(404, "NODE_NOT_AVAILABLE", "Node is not available.")
    definition = get_definition(node_name=node_name, lang=locale)
    payload = definition.model_dump(mode="json")
    payload["documentation"] = await _node_documentation(node_name, locale) or None
    return payload

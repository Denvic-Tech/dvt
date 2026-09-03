from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Header, HTTPException

from services.gateway.deps import get_node_documentation_repository
from services.gateway.utils.detect_locale import detect_locale

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.models.extension import ExtensionRecord
from src.modules.node_documentation.domain.exceptions import (
    NodeDocumentationNotFound,
    UnknownNode,
)
from src.modules.node_documentation.flow.use_cases import GetNodeDocumentation
from src.modules.node_documentation.infra import (
    DSLNodeRegistry,
)
from src.node_dsl import get_all_definitions, get_definition
from src.node_dsl.constants import DVT_ERROR_TEXT_VARIABLE_NAME
from src.node_dsl.node_typing import IO
from src.schemas.http.node_documentation import PublishedNodeDocumentationSchema
from src.schemas.node_definition import BaseVariableDefinitionModel, NodeDefinition

router = r = APIRouter(
    prefix="/nodes",
    tags=["Nodes"],
)

BASE_VARIABLE_DEFINITIONS: dict[str, BaseVariableDefinitionModel] = {
    DVT_ERROR_TEXT_VARIABLE_NAME: BaseVariableDefinitionModel(
        type=IO.STRING,
        required=False,
        description="Runtime error text from an upstream failed node. Available on error branches.",
    )
}


def _with_documentation_flag(
    definition: NodeDefinition,
    *,
    documented_node_names: frozenset[str],
) -> NodeDefinition:
    return definition.model_copy(
        update={
            "documentation_available": definition.name in documented_node_names,
        }
    )


@r.get("/", response_model=dict[str, NodeDefinition])
async def get_node_definitions(
    session: AsyncSessionDepends,
    x_language: Annotated[str | None, Header()] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> dict[str, NodeDefinition]:
    """
    Возвращает определения всех зарегистрированных нод.
    """
    locale = detect_locale(x_language, accept_language)
    definitions = get_all_definitions(lang=locale.value)
    documented_node_names = get_node_documentation_repository().get_documented_node_names()
    enabled_extensions = {
        item.name
        for item in (await session.execute(
            sa.select(ExtensionRecord).where(
                ExtensionRecord.is_enabled == True,
                ExtensionRecord.is_installed == True,
            )
        )).scalars().all()
    }

    return {
        name: _with_documentation_flag(
            definition,
            documented_node_names=documented_node_names,
        )
        for name, definition in definitions.items()
        if not definition.extension_name or definition.extension_name in enabled_extensions
    }


@r.get("/base-variable-definitions", response_model=dict[str, BaseVariableDefinitionModel])
async def get_base_variable_definitions() -> dict[str, BaseVariableDefinitionModel]:
    return BASE_VARIABLE_DEFINITIONS


@r.get("/{node_name}", response_model=NodeDefinition)
async def get_node_definition_by_name(
    node_name: str,
    x_language: str | None = Header(None),
    accept_language: str | None = Header(None),
) -> NodeDefinition:
    locale = detect_locale(x_language, accept_language)
    documented_node_names = get_node_documentation_repository().get_documented_node_names()

    try:
        definition = get_definition(node_name=node_name, lang=locale.value)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return _with_documentation_flag(
        definition,
        documented_node_names=documented_node_names,
    )


@r.get("/{node_name}/documentation", response_model=PublishedNodeDocumentationSchema)
async def get_node_documentation(
    node_name: str,
    x_language: Annotated[str | None, Header()] = None,
    accept_language: Annotated[str | None, Header()] = None,
) -> PublishedNodeDocumentationSchema:
    locale = detect_locale(x_language, accept_language).value
    try:
        documentation = await GetNodeDocumentation(
            repository=get_node_documentation_repository(),
            registry=DSLNodeRegistry(),
        ).execute(node_name=node_name, locale=locale)
    except (NodeDocumentationNotFound, UnknownNode) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return PublishedNodeDocumentationSchema(
        node_name=documentation.node_name,
        locale=documentation.locale,
        content=documentation.content,
    )

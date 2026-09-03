from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Body, Depends

from services.gateway.deps import db_connection as db_connection_deps
from services.gateway.exceptions import project as project_exc

from src.crud import project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.exceptions import SQLQueryMetadataExtractionError
from src.logger import logger
from src.modules.db_connection import ConnectionRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.sql_code_metadata import (
    SQLAlchemyResultMetadataGateway,
    SQLCodeMetadata,
    SQLCodeMetadataProvider,
    SQLGlotParserGateway,
)
from src.modules.sql_template import (
    CallbackSQLExpressionEvaluator,
    SQLTemplateRenderRequest,
    build_render_sql_template_use_case,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.input_expressions import evaluate_input_expression
from src.node_dsl.runtime.connections import resolve_sql_engine
from src.schemas.http.common import ErrorResponse
from src.schemas.internal.project_variables import ProjectVariables
from src.utils.access_control import get_access_scope

router = r = APIRouter()

_sql_code_metadata_use_case = SQLCodeMetadataProvider(
    parser_gateway=SQLGlotParserGateway(),
    result_metadata_gateway=SQLAlchemyResultMetadataGateway(),
).create_extract_sql_code_metadata_use_case()
_sql_template_renderer = build_render_sql_template_use_case()


async def _get_metadata(
        connection: sa.Engine,
        query: str
) -> SQLCodeMetadata:
    normalized_query = query.strip().rstrip(";")
    return _sql_code_metadata_use_case.execute(
        connection=connection,
        sql=normalized_query,
        dialect_name=getattr(connection.dialect, "name", None),
    )


async def _get_user_project(
        *,
        project_id: str,
        session,
        user,
) -> ProjectRecord:
    access_scope = get_access_scope(user)
    project = (await project_crud.get_projects_by(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )).first()
    if project is None:
        raise project_exc.ProjectNotFoundHTTPError(project_id=project_id)
    return project


async def _resolve_project_variables_in_sql_code(
        *,
        sql_code: str,
        project_id: str | None,
        session,
        user,
) -> dict[str, object]:
    if "{{" not in sql_code:
        return {}

    if project_id is None:
        raise SQLQueryMetadataExtractionError(
            "project_id is required when SQL contains project variable templates."
        )

    project = await _get_user_project(
        project_id=project_id,
        session=session,
        user=user,
    )
    return ProjectVariables(variables=project.variables).raw_values


def _evaluate_sql_expression(expression: str, variables, project_variables):
    return evaluate_input_expression(
        expression=expression,
        variables=variables,
        project_variables=project_variables,
        expression_kind="single",
        expression_policy="default",
    )


@r.post(
    "/sql-code-metadata",
    response_model=SQLCodeMetadata,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Ошибка при извлечении метаданных SQL запроса",
        },
    }
)
async def sql_code_metadata(
        sql_code: Annotated[str, Body()],
        db_connection: Annotated[ConnectionRecord, Depends(db_connection_deps.get_user_db_connection_by_body)],
        session: AsyncSessionDepends,
        user: UserAccessOnly,
        project_id: Annotated[str | None, Body(description="Project ID")] = None,
):
    cli = None

    try:
        project_variables = await _resolve_project_variables_in_sql_code(
            sql_code=sql_code,
            project_id=project_id,
            session=session,
            user=user,
        )
        cli = resolve_sql_engine(SqlConnectionRecord(db_connection))
        resolved_sql_code = _sql_template_renderer.execute(
            SQLTemplateRenderRequest(
                template=sql_code,
                variables=project_variables,
                project_variables=project_variables,
                dialect_name=(
                    getattr(getattr(cli, "dialect", None), "name", None)
                    or getattr(db_connection, "type", None)
                ),
                expression_evaluator=CallbackSQLExpressionEvaluator(_evaluate_sql_expression),
            )
        ).sql
        logger.debug(f"Resolved SQL code: {resolved_sql_code}")
        metadata_result = await _get_metadata(
            connection=cli,
            query=resolved_sql_code,
        )

    except SQLQueryMetadataExtractionError:
        raise
    except Exception as e:
        logger.exception(f"Error fetching metadata for connection ID {db_connection.id}: {e}")
        raise SQLQueryMetadataExtractionError(str(e)) from e
    finally:
        if cli is not None:
            dispose = getattr(cli, "dispose", None)
            if callable(dispose):
                dispose()

    return metadata_result

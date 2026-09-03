from fastapi import APIRouter, HTTPException, Response, status

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.ai_mcp_access.domain import (
    InvalidAccessScopeError,
    MCPAccessScope,
    MCPTokenNotFoundError,
)
from src.modules.ai_mcp_access.flow import (
    CreateMCPToken,
    ListMCPToken,
    RevokeMCPToken,
    UpdateMCPToken,
)
from src.modules.ai_mcp_access.infra import SQLAlchemyMCPTokenRepository
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

from .schemas import (
    MCPAccessScopeSchema,
    MCPTokenCreatedSchema,
    MCPTokenCreateSchema,
    MCPTokenListSchema,
    MCPTokenReadSchema,
    MCPTokenUpdateSchema,
)

router = APIRouter(prefix="/mcp-tokens", tags=["MCP Tokens"])


def _scope(schema: MCPAccessScopeSchema) -> MCPAccessScope:
    try:
        return MCPAccessScope.from_mapping(schema.model_dump(mode="json"))
    except InvalidAccessScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _read(token) -> MCPTokenReadSchema:
    return MCPTokenReadSchema(
        id=token.id,
        name=token.name,
        created_at=token.created_at,
        expires_at=token.expires_at,
        access_scope=MCPAccessScopeSchema.model_validate(token.access_scope.to_mapping()),
    )


@router.get("", response_model=MCPTokenListSchema)
async def list_mcp_tokens(
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> MCPTokenListSchema:
    tokens = await ListMCPToken(SQLAlchemyMCPTokenRepository(session)).execute(user_id=user.id)
    return MCPTokenListSchema(items=[_read(token) for token in tokens])


@router.post("", response_model=MCPTokenCreatedSchema, status_code=status.HTTP_201_CREATED)
async def create_mcp_token(
    payload: MCPTokenCreateSchema,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> MCPTokenCreatedSchema:
    result = await CreateMCPToken(SQLAlchemyMCPTokenRepository(session)).execute(
        user_id=user.id,
        name=payload.name,
        expires_at=payload.expires_at,
        access_scope=_scope(payload.access_scope),
    )
    await session.commit()
    return MCPTokenCreatedSchema(**_read(result.token).model_dump(), token=result.raw_token)


@router.patch("/{token_id}", response_model=MCPTokenReadSchema)
async def update_mcp_token(
    token_id: str,
    payload: MCPTokenUpdateSchema,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> MCPTokenReadSchema:
    fields = payload.model_fields_set
    try:
        token = await UpdateMCPToken(SQLAlchemyMCPTokenRepository(session)).execute(
            token_id=token_id,
            user_id=user.id,
            update_name="name" in fields,
            name=payload.name,
            update_expires_at="expires_at" in fields,
            expires_at=payload.expires_at,
            update_access_scope="access_scope" in fields,
            access_scope=_scope(payload.access_scope) if payload.access_scope is not None else None,
        )
    except MCPTokenNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP token not found.") from exc
    await session.commit()
    return _read(token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_mcp_token(
    token_id: str,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
) -> Response:
    try:
        await RevokeMCPToken(SQLAlchemyMCPTokenRepository(session)).execute(
            token_id=token_id,
            user_id=user.id,
        )
    except MCPTokenNotFoundError as exc:
        raise HTTPException(status_code=404, detail="MCP token not found.") from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

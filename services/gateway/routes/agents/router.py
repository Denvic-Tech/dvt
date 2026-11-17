from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse
from redis.asyncio import Redis

from services.gateway.deps.ai_mcp import require_ai_mcp_enabled
from services.gateway.deps.redis import get_redis_bytes
from services.gateway.routes.mcp_tokens.router import _scope

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.logger import logger
from src.modules.agent_connect.domain import (
    AgentConnectCode,
    ConnectCodeClaimLimitError,
    ConnectCodeExpiredError,
    ConnectCodeNotFoundError,
    ConnectCodeRevokedError,
    PublicUrlNotAllowedError,
    normalize_public_url,
    status_of,
)
from src.modules.agent_connect.flow import (
    ClaimConnectCode,
    CreateConnectCode,
    GetConnectCode,
    ListConnectCodes,
    RevokeConnectCode,
)
from src.modules.agent_connect.infra import ValkeyAgentConnectCodeRepository
from src.modules.ai_mcp_access.infra import SQLAlchemyMCPTokenRepository
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

import config

from . import render
from .schemas import (
    ConnectLinkCreatedSchema,
    ConnectLinkCreateSchema,
    ConnectLinkListSchema,
    ConnectLinkReadSchema,
)

router = APIRouter(
    prefix="/agents",
    tags=["Agent connect"],
    dependencies=[Depends(require_ai_mcp_enabled)],
)

RedisDepends = Annotated[Redis, Depends(get_redis_bytes)]

_MARKDOWN = "text/markdown; charset=utf-8"


def _codes(redis: Redis) -> ValkeyAgentConnectCodeRepository:
    return ValkeyAgentConnectCodeRepository(
        redis,
        user_index_ttl_seconds=config.AGENT_CONNECT.RECORD_TTL_SEC,
    )


def _read(code: AgentConnectCode) -> ConnectLinkReadSchema:
    return ConnectLinkReadSchema(
        id=code.id,
        created_at=code.created_at,
        expires_at=code.expires_at,
        status=status_of(code, datetime.now(UTC)),
        claims_count=code.claims_count,
        token_id=code.token_id,
        last_claimed_at=code.last_claimed_at,
    )


@router.post(
    "/connect", response_model=ConnectLinkCreatedSchema, status_code=status.HTTP_201_CREATED
)
async def create_connect_link(
    payload: ConnectLinkCreateSchema,
    user: UserAccessOnly,
    redis: RedisDepends,
) -> ConnectLinkCreatedSchema:
    """Create a one-time link that an AI agent exchanges for its own MCP token."""
    try:
        public_url = normalize_public_url(payload.base_url, config.GATEWAY.GATEWAY_ORIGINS)
    except PublicUrlNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    created = await CreateConnectCode(
        _codes(redis),
        code_ttl_seconds=config.AGENT_CONNECT.CODE_TTL_SEC,
    ).execute(
        user_id=user.id,
        access_scope=_scope(payload.access_scope),
        public_url=public_url,
        token_name=payload.name,
        token_expires_at=payload.token_expires_at,
    )
    return ConnectLinkCreatedSchema(
        id=created.code.id,
        code=created.raw_code,
        connect_url=render.connect_url(public_url, created.raw_code),
        expires_at=created.code.expires_at,
    )


@router.get("/connect", response_model=ConnectLinkListSchema)
async def list_connect_links(user: UserAccessOnly, redis: RedisDepends) -> ConnectLinkListSchema:
    codes = await ListConnectCodes(_codes(redis)).execute(user_id=user.id)
    return ConnectLinkListSchema(items=[_read(code) for code in codes])


@router.delete("/connect/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connect_link(
    code_id: str,
    user: UserAccessOnly,
    redis: RedisDepends,
    session: AsyncSessionDepends,
) -> Response:
    """Revoke the link and, when an agent already claimed it, the MCP token it issued."""
    try:
        await RevokeConnectCode(
            _codes(redis),
            SQLAlchemyMCPTokenRepository(session),
            record_ttl_seconds=config.AGENT_CONNECT.RECORD_TTL_SEC,
        ).execute(code_id=code_id, user_id=user.id)
    except ConnectCodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Connection link not found.") from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/connect/{code}.md", response_class=PlainTextResponse, include_in_schema=False)
async def connect_instruction(code: str, redis: RedisDepends) -> PlainTextResponse:
    """Agent-facing Markdown instruction. Anonymous: the code in the link is the credential."""
    try:
        request = await GetConnectCode(_codes(redis)).execute(raw_code=code)
    except ConnectCodeNotFoundError:
        return PlainTextResponse(
            render.invalid_link_markdown("Такой ссылки нет."),
            status_code=404,
            media_type=_MARKDOWN,
        )
    except ConnectCodeExpiredError:
        return PlainTextResponse(
            render.invalid_link_markdown("Срок действия ссылки истёк."),
            status_code=404,
            media_type=_MARKDOWN,
        )
    except ConnectCodeRevokedError:
        return PlainTextResponse(
            render.invalid_link_markdown("Ссылка отозвана."),
            status_code=404,
            media_type=_MARKDOWN,
        )
    return PlainTextResponse(
        render.render_instruction(request.public_url, code),
        media_type=_MARKDOWN,
    )


@router.get("/claim/{code}", response_class=PlainTextResponse, include_in_schema=False)
async def claim_connect_code(
    code: str,
    redis: RedisDepends,
    session: AsyncSessionDepends,
) -> PlainTextResponse:
    """Exchange the code for an MCP token (plain text). Each claim revokes the previous token."""
    try:
        claimed = await ClaimConnectCode(
            _codes(redis),
            SQLAlchemyMCPTokenRepository(session),
            max_claims=config.AGENT_CONNECT.MAX_CLAIMS,
            record_ttl_seconds=config.AGENT_CONNECT.RECORD_TTL_SEC,
        ).execute(raw_code=code)
    except ConnectCodeNotFoundError:
        return PlainTextResponse("unknown code", status_code=404)
    except ConnectCodeExpiredError:
        return PlainTextResponse("code expired", status_code=410)
    except ConnectCodeRevokedError:
        return PlainTextResponse("code revoked", status_code=410)
    except ConnectCodeClaimLimitError:
        return PlainTextResponse("code used too many times", status_code=410)
    await session.commit()
    logger.info(
        "Agent connect code %s claimed (#%d) by user %s, token %s",
        claimed.code.code_digest[:8],
        claimed.code.claims_count,
        claimed.code.user_id,
        claimed.code.token_id,
    )
    return PlainTextResponse(claimed.raw_token)

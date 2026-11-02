from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.modules.agent_connect.domain import (
    AgentConnectCode,
    ConnectCodeClaimLimitError,
    ConnectCodeExpiredError,
    ConnectCodeNotFoundError,
    ConnectCodeRevokedError,
    ConnectCodeStatus,
    PublicUrlNotAllowedError,
    digest_code,
    generate_code,
    normalize_code,
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
from src.modules.agent_connect.infra.mappers import code_to_hash, hash_to_code
from src.modules.ai_mcp_access.domain import (
    MCPAccessScope,
    MCPToken,
    ResourceScope,
    ResourceScopeMode,
    RevokedMCPTokenError,
    verify_token,
)
from src.modules.ai_mcp_access.flow import AuthenticateMCPToken

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
CODE_TTL = 600
RECORD_TTL = 24 * 3600


class InMemoryCodeRepository:
    def __init__(self) -> None:
        self.codes: dict[str, AgentConnectCode] = {}
        self.ttls: dict[str, int] = {}

    async def get_by_digest(self, code_digest: str) -> AgentConnectCode | None:
        return self.codes.get(code_digest)

    async def get_for_user(self, code_id: str, user_id: str) -> AgentConnectCode | None:
        for code in self.codes.values():
            if code.id == code_id and code.user_id == user_id:
                return code
        return None

    async def list_for_user(self, user_id: str) -> list[AgentConnectCode]:
        return [code for code in self.codes.values() if code.user_id == user_id]

    async def save(self, code: AgentConnectCode, *, ttl_seconds: int) -> AgentConnectCode:
        self.codes[code.code_digest] = code
        self.ttls[code.code_digest] = ttl_seconds
        return code

    async def delete(self, code: AgentConnectCode) -> None:
        self.codes.pop(code.code_digest, None)


class InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, MCPToken] = {}

    async def get_by_id(self, token_id: str) -> MCPToken | None:
        return self.tokens.get(token_id)

    async def get_for_user(self, token_id: str, user_id: str) -> MCPToken | None:
        token = self.tokens.get(token_id)
        return token if token is not None and token.user_id == user_id else None

    async def list_for_user(self, user_id: str) -> list[MCPToken]:
        return [token for token in self.tokens.values() if token.user_id == user_id]

    async def save(self, token: MCPToken) -> MCPToken:
        self.tokens[token.id] = token
        return token


def _scope() -> MCPAccessScope:
    return MCPAccessScope(
        projects=ResourceScope(ResourceScopeMode.SELECTED, frozenset({"project-a"})),
        db_connections=ResourceScope(ResourceScopeMode.ALL),
    )


async def _create(codes: InMemoryCodeRepository, *, now: datetime = NOW, name: str | None = None):
    return await CreateConnectCode(codes, code_ttl_seconds=CODE_TTL).execute(
        user_id="user-a",
        access_scope=_scope(),
        public_url="http://dvt.test",
        token_name=name,
        token_expires_at=None,
        now=now,
    )


def _claimer(
    codes: InMemoryCodeRepository, tokens: InMemoryTokenRepository, *, max_claims: int = 5
):
    return ClaimConnectCode(codes, tokens, max_claims=max_claims, record_ttl_seconds=RECORD_TTL)


def test_generated_code_is_readable_and_normalization_is_forgiving() -> None:
    code = generate_code()

    assert len(code) == 9 and code[4] == "-"
    assert set(code.replace("-", "")) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    assert normalize_code(code.lower().replace("-", " ")) == code
    assert digest_code(code.lower()) == digest_code(code)
    assert generate_code() != code


def test_public_url_must_be_a_known_origin() -> None:
    allowed = ["https://DVT.example.com/", "http://localhost:5173"]

    assert normalize_public_url("https://dvt.example.com", allowed) == "https://dvt.example.com"
    assert normalize_public_url("HTTPS://dvt.example.com/", allowed) == "https://dvt.example.com"
    assert normalize_public_url("http://localhost:5173", allowed) == "http://localhost:5173"
    for bad in (
        "https://evil.example.com",
        "https://dvt.example.com/path",
        "https://dvt.example.com?x=1",
        "https://user@dvt.example.com",
        "ftp://dvt.example.com",
        "dvt.example.com",
        "",
    ):
        with pytest.raises(PublicUrlNotAllowedError):
            normalize_public_url(bad, allowed)


@pytest.mark.asyncio
async def test_create_stores_only_digest_with_code_ttl() -> None:
    codes = InMemoryCodeRepository()

    created = await _create(codes, name="  Codex  ")

    assert created.code.code_digest == digest_code(created.raw_code)
    assert created.raw_code not in code_to_hash(created.code).values()
    assert created.code.expires_at == NOW + timedelta(seconds=CODE_TTL)
    assert created.code.token_name == "Codex"
    assert created.code.public_url == "http://dvt.test"
    assert created.code.token_id is None
    assert codes.ttls[created.code.code_digest] == CODE_TTL
    assert status_of(created.code, NOW) is ConnectCodeStatus.PENDING


@pytest.mark.asyncio
async def test_claim_issues_token_for_owner_with_request_scope() -> None:
    codes, tokens = InMemoryCodeRepository(), InMemoryTokenRepository()
    created = await _create(codes)

    claimed = await _claimer(codes, tokens).execute(raw_code=created.raw_code, now=NOW)

    token = await AuthenticateMCPToken(tokens).execute(raw_token=claimed.raw_token)
    assert token.user_id == "user-a"
    assert token.access_scope == _scope()
    assert token.name == "Agent connect 2026-10-29 12:00 UTC"
    assert claimed.code.token_id == token.id
    assert claimed.code.claims_count == 1
    assert claimed.code.last_claimed_at == NOW
    assert codes.ttls[created.code.code_digest] == RECORD_TTL
    assert status_of(claimed.code, NOW) is ConnectCodeStatus.CLAIMED


@pytest.mark.asyncio
async def test_repeated_claim_rotates_token_and_revokes_previous_one() -> None:
    codes, tokens = InMemoryCodeRepository(), InMemoryTokenRepository()
    created = await _create(codes)
    claimer = _claimer(codes, tokens)

    first = await claimer.execute(raw_code=created.raw_code, now=NOW)
    second = await claimer.execute(raw_code=created.raw_code, now=NOW + timedelta(minutes=1))

    assert first.raw_token != second.raw_token
    with pytest.raises(RevokedMCPTokenError):
        verify_token(tokens.tokens[first.code.token_id or ""], first.raw_token)
    assert (await AuthenticateMCPToken(tokens).execute(raw_token=second.raw_token)).id == (
        second.code.token_id
    )
    assert second.code.claims_count == 2


@pytest.mark.asyncio
async def test_claim_limit_expiry_and_unknown_code() -> None:
    codes, tokens = InMemoryCodeRepository(), InMemoryTokenRepository()
    created = await _create(codes)
    claimer = _claimer(codes, tokens, max_claims=2)

    await claimer.execute(raw_code=created.raw_code, now=NOW)
    await claimer.execute(raw_code=created.raw_code, now=NOW)
    with pytest.raises(ConnectCodeClaimLimitError):
        await claimer.execute(raw_code=created.raw_code, now=NOW)

    late = NOW + timedelta(seconds=CODE_TTL)
    with pytest.raises(ConnectCodeExpiredError):
        await _claimer(codes, tokens).execute(raw_code=created.raw_code, now=late)
    with pytest.raises(ConnectCodeExpiredError):
        await GetConnectCode(codes).execute(raw_code=created.raw_code, now=late)
    with pytest.raises(ConnectCodeNotFoundError):
        await claimer.execute(raw_code="ZZZZ-ZZZZ", now=NOW)


@pytest.mark.asyncio
async def test_unclaimed_code_expires_and_instruction_is_readable_until_then() -> None:
    codes = InMemoryCodeRepository()
    created = await _create(codes)

    readable = await GetConnectCode(codes).execute(raw_code=created.raw_code, now=NOW)
    assert readable.id == created.code.id
    assert status_of(created.code, NOW + timedelta(seconds=CODE_TTL)) is ConnectCodeStatus.EXPIRED


@pytest.mark.asyncio
async def test_revoke_disables_link_and_issued_token() -> None:
    codes, tokens = InMemoryCodeRepository(), InMemoryTokenRepository()
    created = await _create(codes)
    claimed = await _claimer(codes, tokens).execute(raw_code=created.raw_code, now=NOW)

    revoked = await RevokeConnectCode(codes, tokens, record_ttl_seconds=RECORD_TTL).execute(
        code_id=created.code.id,
        user_id="user-a",
    )

    assert status_of(revoked, NOW) is ConnectCodeStatus.REVOKED
    with pytest.raises(RevokedMCPTokenError):
        await AuthenticateMCPToken(tokens).execute(raw_token=claimed.raw_token)
    with pytest.raises(ConnectCodeRevokedError):
        await _claimer(codes, tokens).execute(raw_code=created.raw_code, now=NOW)
    with pytest.raises(ConnectCodeNotFoundError):
        await RevokeConnectCode(codes, tokens, record_ttl_seconds=RECORD_TTL).execute(
            code_id=created.code.id,
            user_id="someone-else",
        )


@pytest.mark.asyncio
async def test_list_is_newest_first() -> None:
    codes = InMemoryCodeRepository()
    older = await _create(codes, now=NOW - timedelta(minutes=5))
    newer = await _create(codes, now=NOW)

    listed = await ListConnectCodes(codes).execute(user_id="user-a")

    assert [code.id for code in listed] == [newer.code.id, older.code.id]


@pytest.mark.asyncio
async def test_hash_mapping_round_trips_including_bytes_payloads() -> None:
    codes, tokens = InMemoryCodeRepository(), InMemoryTokenRepository()
    created = await _create(codes, name="Claude")
    claimed = await _claimer(codes, tokens).execute(raw_code=created.raw_code, now=NOW)

    as_hash = code_to_hash(claimed.code)
    as_bytes = {key.encode(): value.encode() for key, value in as_hash.items()}

    assert hash_to_code(as_hash) == claimed.code
    assert hash_to_code(as_bytes) == claimed.code
    assert hash_to_code(code_to_hash(created.code)) == created.code

from src.models.user_tokens import UsersTokenRecord

from ..domain.entities import MCPToken
from ..domain.types import MCP_TOKEN_TYPE
from ..domain.value_objects import MCPAccessScope


def token_record_to_domain(record: UsersTokenRecord) -> MCPToken:
    return MCPToken(
        id=str(record.id),
        user_id=record.user_id,
        token_digest=record.token,
        name=record.name,
        access_scope=MCPAccessScope.from_mapping(record.access_scope),
        created_at=record.created_at,
        expires_at=record.expires_at,
        is_deleted=record.is_deleted,
    )


def apply_domain_token(record: UsersTokenRecord, token: MCPToken) -> UsersTokenRecord:
    record.token = token.token_digest
    record.token_type = MCP_TOKEN_TYPE
    record.name = token.name
    record.access_scope = token.access_scope.to_mapping()
    record.expires_at = token.expires_at
    record.is_deleted = token.is_deleted
    return record

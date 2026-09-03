import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_tokens import UsersTokenRecord

from ...domain.entities import MCPToken
from ...domain.repositories import MCPTokenRepository
from ...domain.types import MCP_TOKEN_TYPE
from ..mappers import apply_domain_token, token_record_to_domain


class SQLAlchemyMCPTokenRepository(MCPTokenRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, token_id: str) -> MCPToken | None:
        record = (
            await self._session.execute(
                sa.select(UsersTokenRecord).where(
                    UsersTokenRecord.id == token_id,
                    UsersTokenRecord.token_type == MCP_TOKEN_TYPE,
                )
            )
        ).scalar_one_or_none()
        return None if record is None else token_record_to_domain(record)

    async def get_for_user(self, token_id: str, user_id: str) -> MCPToken | None:
        record = (
            await self._session.execute(
                sa.select(UsersTokenRecord).where(
                    UsersTokenRecord.id == token_id,
                    UsersTokenRecord.user_id == user_id,
                    UsersTokenRecord.token_type == MCP_TOKEN_TYPE,
                )
            )
        ).scalar_one_or_none()
        return None if record is None else token_record_to_domain(record)

    async def list_for_user(self, user_id: str) -> list[MCPToken]:
        records = (
            (
                await self._session.execute(
                    sa.select(UsersTokenRecord)
                    .where(
                        UsersTokenRecord.user_id == user_id,
                        UsersTokenRecord.token_type == MCP_TOKEN_TYPE,
                        UsersTokenRecord.is_deleted.is_(False),
                    )
                    .order_by(UsersTokenRecord.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [token_record_to_domain(record) for record in records]

    async def save(self, token: MCPToken) -> MCPToken:
        record = await self._session.get(UsersTokenRecord, token.id)
        if record is None:
            record = UsersTokenRecord(
                id=token.id,
                user_id=token.user_id,
                token=token.token_digest,
                token_type=MCP_TOKEN_TYPE,
                name=token.name,
                access_scope=token.access_scope.to_mapping(),
                expires_at=token.expires_at,
                created_at=token.created_at,
                is_deleted=token.is_deleted,
                whitelisted_ip_addresses=None,
            )
        else:
            if record.user_id != token.user_id or record.token_type != MCP_TOKEN_TYPE:
                raise ValueError("Token identity cannot be changed.")
            apply_domain_token(record, token)
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return token_record_to_domain(record)

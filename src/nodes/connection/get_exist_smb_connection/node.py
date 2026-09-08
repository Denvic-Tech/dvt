import sqlalchemy.ext.asyncio as asa
from db_connection import AccessDeniedError, ConnectionNotFoundError

from core.metadata import load_smb_metadata

from src.db import async_engine
from src.logger import logger
from src.modules.db_connection import build_resolve_connection_client_use_case
from src.modules.db_connection.infra.connectors.smbprotocol.schemas import (
    SMBProtocolProperties,
    SMBProtocolSecrets,
)
from src.modules.user import User, build_get_user_by_id_use_case
from src.modules.user.flow.exceptions import UserNotFoundError
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl import (
    IO,
    InputField,
    OutputField,
    SMBConnectionOutputBaseNode,
    SMBConnectionRecord,
)
from src.node_dsl.types import NodeMetadata

import config


class GetExistSMBConnection(SMBConnectionOutputBaseNode):
    TITLE = "SMB Connection"
    EMOJI = "🗂️"
    CATEGORY = "Connections"
    CACHABLE = False

    connection_id: IO.SMB_CONNECTION_ID = InputField()

    connection: SMBConnectionRecord = OutputField()

    async def _get_user(self) -> User:
        async with asa.AsyncSession(async_engine) as session:
            use_case = build_get_user_by_id_use_case(session)
            return await use_case.execute(user_id=self.user_id)

    async def _get_connection_from_db(self):
        try:
            user = await self._get_user()
            if user is None:
                logger.error(
                    f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
                )
                raise ValueError(
                    f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
                )

            use_case = build_resolve_connection_client_use_case(
                engine=async_engine,
                fernet_key=config.SECURITY.FERNET_KEY,
                user_repository_factory=SQLAlchemyUserRepository
            )
            resolved = await use_case.execute(connection_id=self.connection_id, actor=user)
        except (UserNotFoundError, AccessDeniedError, ConnectionNotFoundError):
            logger.error(
                f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
            )
            raise ValueError(
                f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
            ) from None

        if resolved.connection.type == "smbprotocol":
            return SMBConnectionRecord(resolved.connection)

        logger.error(f"Connection with ID {self.connection_id} is not a SMB connection.")
        raise TypeError(f"Connection with ID {self.connection_id} is not a SMB connection.")

    async def process(self):
        self.connection = await self._get_connection_from_db()

    def infer_metadata(self) -> NodeMetadata:
        connection_properties = SMBProtocolProperties.model_validate(self.connection.properties)
        connection_secrets = SMBProtocolSecrets.model_validate(self.connection.secrets)

        return {
            "connection": load_smb_metadata(
                connection_id=self.connection_id,
                host=connection_properties.host,
                port=connection_properties.port,
                share=connection_properties.share,
                username=connection_properties.username,
                password=connection_secrets.password,
            )
        }

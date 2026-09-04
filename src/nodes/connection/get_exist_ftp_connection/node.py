import sqlalchemy.ext.asyncio as asa
from db_connection import AccessDeniedError, ConnectionNotFoundError
from db_connection.connectors.ftp import FTPProperties, FTPSecrets, SFTPProperties, SFTPSecrets

from core.metadata import load_ftp_metadata

from src.db import async_engine
from src.logger import logger
from src.modules.db_connection import build_resolve_connection_client_use_case
from src.modules.user import User, build_get_user_by_id_use_case
from src.modules.user.flow.exceptions import UserNotFoundError
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl import (
    IO,
    FTPConnectionOutputBaseNode,
    FTPConnectionRecord,
    InputField,
    OutputField,
)
from src.node_dsl.types import NodeMetadata

import config


class GetExistFTPConnection(FTPConnectionOutputBaseNode):
    TITLE = "FTP Connection"
    EMOJI = "📁"
    CATEGORY = "Connections"
    CACHABLE = False

    # --- Inputs ---
    connection_id: IO.FTP_CONNECTION_ID = InputField()

    # --- Outputs ---
    connection: FTPConnectionRecord = OutputField()

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

        if resolved.connection.type in {"ftp", "sftp"}:
            return FTPConnectionRecord(resolved.connection)

        logger.error(f"Connection with ID {self.connection_id} is not a (S)FTP connection.")
        raise TypeError(f"Connection with ID {self.connection_id} is not a (S)FTP connection.")

    async def process(self):
        self.connection = await self._get_connection_from_db()

    def infer_metadata(self) -> NodeMetadata:
        """
        Вычисляет метаданные для FTP подключения.
        Возвращает информацию о хосте и содержимом начальной директории.
        """
        if self.connection.type == "sftp":
            connection_properties = SFTPProperties.model_validate(self.connection.properties)
            connection_secrets = SFTPSecrets.model_validate(self.connection.secrets)
            username = connection_properties.username
            password = connection_secrets.password
            mode = "sftp"
            anonymous = False
            encoding = "utf-8"
            certfile = None
            keyfile = None
            initial_directory = connection_properties.initial_directory
            host = connection_properties.host
            port = connection_properties.port
        else:
            connection_properties = FTPProperties.model_validate(self.connection.properties)
            connection_secrets = FTPSecrets.model_validate(self.connection.secrets)
            username = connection_properties.username
            password = connection_secrets.password
            mode = connection_properties.mode
            anonymous = connection_properties.anonymous
            encoding = connection_properties.encoding
            certfile = connection_properties.certfile
            keyfile = connection_properties.keyfile
            initial_directory = connection_properties.initial_directory
            host = connection_properties.host
            port = connection_properties.port

        return {
            "connection": load_ftp_metadata(
                connection_id=self.connection_id,
                host=host,
                port=port,
                mode=mode,
                username=username,
                password=password,
                anonymous=anonymous,
                encoding=encoding,
                initial_directory=initial_directory,
                certfile=certfile,
                keyfile=keyfile,
            )
        }

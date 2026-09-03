import sqlalchemy.ext.asyncio as asa
from cachetools import TTLCache
from db_connection import AccessDeniedError, ConnectionNotFoundError
from db_connection.registry.defaults import S3Properties, S3Secrets

from core.metadata import load_s3_metadata

from src.db import async_engine
from src.logger import logger
from src.modules.db_connection import build_resolve_connection_client_use_case
from src.modules.user import User, build_get_user_by_id_use_case
from src.modules.user.flow.exceptions import UserNotFoundError
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl import IO, InputField, OutputField, S3ConnectionOutputBaseNode, S3ConnectionRecord
from src.node_dsl.types import NodeMetadata

import config

meta_cache_key_by_id = TTLCache(maxsize=100, ttl=10 * 60)


class GetExistS3Connection(S3ConnectionOutputBaseNode):
    TITLE = "S3 Connection"
    EMOJI = "☁️"
    CATEGORY = "Connections"
    CACHABLE = False

    # --- Inputs ---
    connection_id: IO.S3_CONNECTION_ID = InputField()

    # --- Outputs ---
    connection: S3ConnectionRecord = OutputField()

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

        if resolved.connection.type in {"s3"}:
            return S3ConnectionRecord(resolved.connection)

        logger.error(f"Connection with ID {self.connection_id} is not a S3 connection.")
        raise TypeError(f"Connection with ID {self.connection_id} is not a S3 connection.")

    def get_metadata_cache_key(self) -> str:
        key = f"{self.user_id}:{self.connection_id}"
        meta_cache_key = meta_cache_key_by_id.get(key)

        if meta_cache_key is None:
            # For S3, we can create a cache key based on the connection config
            # Using a simple hash of connection_id since S3 doesn't have schema like SQL databases
            meta_cache_key = f"s3_{self.connection_id}"
            meta_cache_key_by_id[key] = meta_cache_key

        return meta_cache_key

    async def process(self):
        self.connection = await self._get_connection_from_db()

    def infer_metadata(self) -> NodeMetadata:
        """
        Вычисляет метаданные для S3 подключения.
        Возвращает информацию о бакетах и объектах.
        """
        connection_properties = S3Properties.model_validate(self.connection.properties)
        connection_secrets = S3Secrets.model_validate(self.connection.secrets)
        return {
            "connection": load_s3_metadata(
                bucket=connection_properties.bucket,
                region_name=connection_properties.region_name,
                endpoint_url=connection_properties.endpoint_url,
                access_token_id=connection_secrets.access_token_id,
                access_token_key=connection_secrets.access_token_key,
                session_token=connection_secrets.session_token,
                use_ssl=connection_properties.use_ssl,
                path_style=connection_properties.path_style,
                signature_version=connection_properties.signature_version,
                prefix=connection_properties.prefix,
                connection_id=self.connection_id,
                verify=False,
            )
        }

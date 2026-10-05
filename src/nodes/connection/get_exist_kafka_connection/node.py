import sqlalchemy.ext.asyncio as asa
from db_connection import AccessDeniedError, ConnectionNotFoundError

from core.metadata import build_kafka_metadata

from src import utils
from src.db import async_engine
from src.logger import logger
from src.modules.db_connection import build_connection_service
from src.modules.kafka_consumption.facade import build_kafka_gateway
from src.modules.user import User, build_get_user_by_id_use_case
from src.modules.user.flow.exceptions import UserNotFoundError
from src.modules.user.infra.repositories import SQLAlchemyUserRepository
from src.node_dsl import (
    IO,
    InputField,
    KafkaConnectionOutputBaseNode,
    KafkaConnectionRecord,
    OutputField,
)

import config


class GetExistKafkaConnection(KafkaConnectionOutputBaseNode):
    TITLE = "Kafka Connection"
    ICON_KEY = "kafka-connection"
    CATEGORY = "Connections"
    CACHABLE = False
    EXPERIMENTAL = False
    DESCRIPTION = "Load an accessible saved Kafka connection for explicit batch reading and commit."


    # --- Inputs ---
    connection_id: IO.KAFKA_CONNECTION_ID = InputField(
        agent_description=(
            "Use "
            "the catalog ID (a string) of an existing Kafka connection accessible to the executing user; do "
            "not use a topic ID or another connection type. Resolve the saved connection from "
            "available catalog information rather than inventing credentials or identifiers."
        ),
    )

    # --- Outputs ---
    connection: KafkaConnectionRecord = OutputField()

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

            use_case = build_connection_service(
                engine=async_engine,
                fernet_key=config.SECURITY.FERNET_KEY,
                user_repository_factory=SQLAlchemyUserRepository
            )
            record = await use_case.get(str(self.connection_id), actor=user)
        except (UserNotFoundError, AccessDeniedError, ConnectionNotFoundError):
            logger.error(
                f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
            )
            raise ValueError(
                f"No DB connection found with ID {self.connection_id} for user {self._user_id}"
            ) from None

        if str(record.type).lower() == "kafka":
            return KafkaConnectionRecord(record)

        logger.error(f"Connection with ID {self.connection_id} is not a Kafka connection.")
        raise TypeError(f"Connection with ID {self.connection_id} is not a Kafka connection.")

    async def process(self):
        self.connection = await self._get_connection_from_db()

    async def infer_metadata(self):
        connection = getattr(self, "connection", None)
        if not isinstance(connection, KafkaConnectionRecord):
            connection = await self._get_connection_from_db()

        gateway = build_kafka_gateway(
            properties=connection.properties,
            secrets=connection.secrets,
            check_cancelled=self.cancellation.raise_if_requested,
        )
        snapshot = await utils.async_run_callable(gateway.describe_metadata)
        return {
            "connection": build_kafka_metadata(
                cluster_metadata=snapshot["cluster"],
                topics_metadata=snapshot["topics"],
                bootstrap_servers=connection.properties.get("bootstrap_servers"),
            )
        }

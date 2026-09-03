from db_connection.infra import DefaultStoredConnection
from sqlmodel import Field


class DVTStoredConnectionRecord(DefaultStoredConnection, table=True):
    __tablename__ = "connections_v1"

    user_id: str = Field(
        foreign_key="users.id",
        nullable=False,
        description="ID пользователя, которому принадлежит соединение",
    )
    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID организации, которой принадлежит соединение",
    )

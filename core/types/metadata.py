from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from .column import Column
from .db_table import DBDatabase, DBDialect, DBSchema, DBTable
from .ftp import FTPDirectoryMetadata
from .json_metadata import (
    JSONFlattenCandidate,
    JSONStructureNode,
    JSONStructureStats,
)
from .kafka import KafkaCluster, KafkaTopic
from .s3 import S3Bucket
from .smb import SMBDirectoryMetadata


class MetadataType(StrEnum):
    DATAFRAME = "DATAFRAME"
    DATABASE = "DATABASE"
    KAFKA = "KAFKA"
    SERIES = "SERIES"
    S3 = "S3"
    FTP = "FTP"
    SMB = "SMB"
    JSON = "JSON"
    TABLE_SCHEMA = "TABLE_SCHEMA"

    def __str__(self):
        return self.value


class MetadataBase(BaseModel):
    type: MetadataType = Field(..., description="Тип метаданных")

    class Config:
        discriminator = "type"


class SeriesMetadata(MetadataBase):
    type: Literal[MetadataType.SERIES] = MetadataType.SERIES

    name: str = Field(description="Имя колонки")

    column_data: Column


class DataFrameMetadata(MetadataBase):
    """Метаданные DataFrame."""

    type: Literal[MetadataType.DATAFRAME] = MetadataType.DATAFRAME

    columns: list[Column]

    # TODO: Придумать как вытаскивать количество строк и размер из Dask
    rows_num: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=0, description="Размер DataFrame в байтах")


class TableSchemaColumnMetadata(BaseModel):
    """Transport-представление колонки доменной TableSchema."""

    name: str
    dtype: str | None = None
    description: str | None = None
    nullable: bool | None = None
    default: Any = None
    order: int | None = Field(default=None, ge=0)
    primary_key: bool | None = None
    unique: bool | None = None
    precision: int | None = Field(default=None, ge=0)
    scale: int | None = Field(default=None, ge=0)
    length: int | None = Field(default=None, ge=0)
    format: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableSchemaMetadata(MetadataBase):
    """Метаданные схемы таблицы, доступные UI без доступа к runtime-объекту."""

    type: Literal[MetadataType.TABLE_SCHEMA] = MetadataType.TABLE_SCHEMA
    columns: list[TableSchemaColumnMetadata] = Field(default_factory=list)


class JSONMetadata(MetadataBase):
    type: Literal[MetadataType.JSON] = MetadataType.JSON
    response: Any = None
    root: JSONStructureNode | None = Field(
        default=None, description="Inferred JSON structure root."
    )
    flatten_candidates: list[JSONFlattenCandidate] = Field(
        default_factory=list,
        description="Suggested paths for JSON normalization.",
    )
    stats: JSONStructureStats | None = Field(
        default=None, description="Aggregated JSON structure statistics."
    )
    inferred_schema: dict[str, Any] | None = Field(
        default=None,
        description="Schema-like serialized representation of the inferred JSON structure.",
    )
    structure_truncated: bool = Field(
        default=False,
        description="Whether inference was truncated because of configured limits.",
    )


class DBMetadata(MetadataBase):
    """
    Модель, представляющая полные метаданные соединения с базой данных.
    """

    type: Literal[MetadataType.DATABASE] = MetadataType.DATABASE

    connection_id: str | None = Field(
        default=None,
        description="Идентификатор подключения для ленивой загрузки каталога через Gateway.",
    )
    connection_revision: str | None = Field(
        default=None,
        description="Ревизия подключения, меняющаяся при его обновлении.",
    )
    catalog_mode: Literal["embedded", "lazy"] = Field(
        default="embedded",
        description="Способ доставки каталога: внутри metadata или лениво через Gateway.",
    )
    catalog_capabilities: "DBCatalogCapabilities | None" = Field(
        default=None,
        description="Поддерживаемые уровни ленивого каталога.",
    )

    dialect: DBDialect = Field(..., description="Диалект базы данных")

    databases: list[DBDatabase] = Field(default_factory=list, description="Список баз данных.")
    schemas: list[DBSchema] = Field(default_factory=list, description="Список схем в соединении.")
    tables: list[DBTable] = Field(
        default_factory=list, description="Список таблиц в корне метаданных."
    )

    database_name: str | None = Field(None, description="Имя базы данных.")
    connection_string: str | None = Field(
        None, description="Строка подключения к базе данных (без учетных данных)."
    )

    def iter_tables(self) -> list[DBTable]:
        tables: list[DBTable] = [*self.tables]
        for schema in self.schemas:
            tables.extend(schema.tables)
        for database in self.databases:
            tables.extend(database.tables)
            for schema in database.schemas:
                tables.extend(schema.tables)
        return tables

    def find_table(
        self,
        *,
        table_name: str,
        schema_name: str | None = None,
        database_name: str | None = None,
    ) -> DBTable | None:
        for table in self.iter_tables():
            if table.name != table_name:
                continue
            if schema_name is not None and table.schema_name != schema_name:
                continue
            if database_name is not None and table.database_name != database_name:
                continue
            return table
        return None


class DBCatalogCapabilities(BaseModel):
    supports_databases: bool = False
    supports_schemas: bool = False
    supports_tables: bool = True
    supports_views: bool = True
    supports_search: bool = True
    max_page_size: int = Field(default=200, ge=1)


class KafkaMetadata(MetadataBase):
    type: Literal[MetadataType.KAFKA] = MetadataType.KAFKA

    cluster: KafkaCluster
    topics: list[KafkaTopic]
    bootstrap_servers: list[str]
    connection_string: str


class S3Metadata(MetadataBase):
    """
    Модель, представляющая метаданные S3 подключения.
    """

    type: Literal[MetadataType.S3] = MetadataType.S3

    connection_id: str = Field(description="Connection ID")
    connection_prefix: str | None = Field(None, description="Connection prefix")
    bucket: S3Bucket = Field(default_factory=list, description="Метаданные бакета в S3.")
    endpoint_url: str | None = Field(
        None, description="URL эндпоинта S3 (для совместимых S3 хранилищ)."
    )
    region: str | None = Field(None, description="Регион S3.")
    connection_string: str | None = Field(
        None, description="Строка подключения к S3 (без учетных данных)."
    )


class FTPMetadata(MetadataBase):
    """
    Метаданные FTP подключения.
    """

    type: Literal[MetadataType.FTP] = MetadataType.FTP

    connection_id: str = Field(description="Connection ID")
    connection_string: str | None = Field(None, description="Безопасная строка подключения")
    connection_prefix: str | None = Field(None, description="Connection prefix")

    host: str = Field(description="Хост FTP сервера")
    port: int = Field(21, description="Порт")
    mode: str = Field("ftp", description="Режим (ftp/ftps)")

    username: str | None = Field(None, description="Имя пользователя")
    anonymous: bool = Field(False, description="Анонимный вход")

    initial_directory: str | None = Field(None, description="Стартовый каталог")
    encoding: str = Field("utf-8", description="Кодировка")

    directory: FTPDirectoryMetadata | None = Field(
        None, description="Метаданные начальной директории"
    )


class SMBMetadata(MetadataBase):
    type: Literal[MetadataType.SMB] = MetadataType.SMB

    connection_id: str = Field(description="Connection ID")
    connection_string: str | None = Field(None, description="Безопасная строка подключения")
    connection_prefix: str | None = Field(None, description="Connection prefix")

    host: str = Field(description="Хост SMB сервера")
    port: int = Field(445, description="Порт")
    share: str = Field(description="Имя SMB share")

    username: str | None = Field(None, description="Имя пользователя")
    initial_directory: str | None = Field("/", description="Стартовый каталог внутри share")

    directory: SMBDirectoryMetadata | None = Field(
        None, description="Метаданные текущей директории SMB"
    )


Metadata = Annotated[
    DataFrameMetadata
    | DBMetadata
    | KafkaMetadata
    | SeriesMetadata
    | S3Metadata
    | JSONMetadata
    | FTPMetadata
    | SMBMetadata
    | TableSchemaMetadata,
    Field(discriminator="type"),
]

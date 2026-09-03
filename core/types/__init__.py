from pystructor import rebuild_all_models

from .column import Column
from .common import DataFrameLike
from .data_type import DataType
from .db_column import DBColumn
from .db_table import DBDatabase, DBDialect, DBSchema, DBTable, DBTableType
from .df_data import DataFrameData
from .filesystem import FsCtx
from .ftp import FTPDirectoryMetadata, FTPFile, FTPFolder, FTPNode, FTPNodeBase
from .json_metadata import (
    JSONFlattenCandidate,
    JSONFlattenCandidateKind,
    JSONNodeKind,
    JSONStructureNode,
    JSONStructureStats,
)
from .kafka import KafkaBroker, KafkaCluster, KafkaTopic
from .metadata import (
    DataFrameMetadata,
    DBCatalogCapabilities,
    DBMetadata,
    FTPMetadata,
    JSONMetadata,
    KafkaMetadata,
    Metadata,
    MetadataType,
    S3Metadata,
    SMBMetadata,
    TableSchemaColumnMetadata,
    TableSchemaMetadata,
)
from .s3 import S3Bucket, S3File, S3Folder, S3Node, S3NodeBase, S3Object
from .smb import SMBDirectoryMetadata, SMBFile, SMBFolder, SMBNode, SMBNodeBase

rebuild_all_models(locals())

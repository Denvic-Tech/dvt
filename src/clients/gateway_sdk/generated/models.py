from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, RootModel


class SDKBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


AIAnalysisStatus: TypeAlias = Literal['queued', 'running', 'success', 'error']

AIServiceAnalysisClassification: TypeAlias = Literal['user_pipeline_error', 'dvt_bug', 'infra_error', 'unknown']

AIServiceAnalysisSeverity: TypeAlias = Literal['low', 'medium', 'high']

DBTableType: TypeAlias = Literal['BASE_TABLE', 'VIEW', 'TEMPORARY', 'SYSTEM', 'UNKNOWN']

DVTDefaultRoles: TypeAlias = Literal['superadmin', 'admin', 'user']

DataType: TypeAlias = Literal['INT', 'FLOAT', 'STRING', 'BOOLEAN', 'DATETIME', 'TIMEDELTA', 'CATEGORY', 'DICTIONARY', 'OBJECT', 'UNKNOWN']

ExceptionCategory: TypeAlias = Literal['DATABASE', 'DATAFRAME', 'GATEWAY_ADMIN', 'GATEWAY_EXCEPTION_REGISTRY', 'GATEWAY_INTERNAL', 'GATEWAY_PROJECT', 'GATEWAY_PROJECT', 'GATEWAY_PUBLIC', 'GATEWAY_STORAGE', 'GATEWAY_UTILS', 'GATEWAY_QUEUE', 'GATEWAY_WS', 'GATEWAY_CACHE', 'TASK_WORKER_CACHE', 'TASK_WORKER_TASKS', 'PROJECT_SCHEDULER_TASKS', 'WORKER_CLIENT', 'ORCHESTRATOR_CLIENT', 'SCHEDULER_CLIENT', 'S3', 'FTP', 'high', 'critical', 'UNKNOWN', 'USER', 'ORGANIZATION', 'PROJECT', 'TASK', 'QUEUE_TOPIC', 'GRAPH', 'GRAPH_NODE', 'GRAPH_EDGE', 'SUBGRAPH', 'NODES', 'CRUD_USER', 'CRUD_ORGANIZATION', 'CRUD_PROJECT', 'CRUD_PROJECT_SCHEDULE', 'CRUD_DB_CONNECTION', 'CRUD_QUEUE_TOPIC', 'CRUD_TASK', 'CRUD_GRAPH', 'CRUD_GRAPH_NODE', 'CRUD_GRAPH_EDGE', 'CRUD_SUBGRAPH']

PipelineExecutionMode: TypeAlias = Literal['full', 'metadata_only']

ExtensionDepsStatus: TypeAlias = Literal['not_installed', 'installing', 'ready', 'error']

ExtensionLicenseStatus: TypeAlias = Literal['not_required', 'inactive', 'active', 'expired']

FTPMode: TypeAlias = Literal['ftp', 'ftps_implicit', 'ftps_explicit']

IO: TypeAlias = Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DICT', 'JSON', 'DATAFRAME', 'COLUMN', 'COLUMN_NAME', 'DB_CONNECTION', 'DB_CONNECTION_ID', 'S3_CONNECTION,FTP_CONNECTION,SMB_CONNECTION', 'S3_CONNECTION', 'S3_CONNECTION_ID', 'FTP_CONNECTION', 'FTP_CONNECTION_ID', 'SMB_CONNECTION', 'SMB_CONNECTION_ID', 'KAFKA_CONNECTION', 'KAFKA_CONNECTION_ID', 'DATETIME', 'TIMEDELTA', 'OBJECT', 'UNKNOWN', 'SCHEMA', 'VARIABLE', 'SIGNAL', '*', 'FLOAT,INT', 'PRIMITIVE']

NoDriverOptions: TypeAlias = dict[str, Any]

NodeType: TypeAlias = Literal['BASE', 'DATAFRAME_OUTPUT', 'CONNECTION_OUTPUT', 'PRIMITIVE', 'INTERNAL', 'TESTING', 'WIDGET']

OOMGuardMode: TypeAlias = Literal['DISABLED', 'HOST_PRESSURE', 'WORKER_THRESHOLD']

OOMWorkerThresholdType: TypeAlias = Literal['PERCENT', 'ABSOLUTE_MB']

QueueAction: TypeAlias = Literal['cancel']

TaskSource: TypeAlias = Literal['UI', 'API', 'SCHEDULER', 'NODE']

TaskStatus: TypeAlias = Literal['IDLE', 'QUEUED', 'ASSIGNED', 'PENDING', 'STARTED', 'RUNNING', 'SUCCESS', 'ERROR', 'CANCELLED', 'CANCEL_REQUESTED']

WorkerStatus: TypeAlias = Literal['online', 'offline', 'unlicensed']

ApiTokenEmptyData: TypeAlias = dict[str, Any]

ExecutionStatus: TypeAlias = Literal['idle', 'running', 'success', 'error', 'cancelled']

JSONFlattenCandidateKind: TypeAlias = Literal['RECORD_PATH', 'META_PATH', 'EXPLODE_PATH']

JSONNodeKind: TypeAlias = Literal['OBJECT', 'ARRAY', 'STRING', 'INTEGER', 'NUMBER', 'BOOLEAN', 'NULL', 'UNION', 'UNKNOWN']

DBDialect: TypeAlias = Literal['postgresql', 'mysql', 'mariadb', 'mongodb', 'mssql', 'sqlserver', 'clickhouse', 'sqlite', 'oracle'] | str

EventType: TypeAlias = Literal['PING', 'STATUS', 'NODE_METADATA', 'NODE_EXECUTION_STATUS', 'TASK_EXECUTION_STATUS', 'TASK_EXECUTION_TELEMETRY', 'PROGRESS', 'LOG_EVENT']

LiteralInputDefinitionKey: TypeAlias = Literal['input_variables', 'signal_in']

LiteralOutputDefinitionKey: TypeAlias = Literal['output_variables', 'signal_out', 'signal_error']

InputDefinitionKey: TypeAlias = str | Literal['input_variables', 'signal_in']

OutputDefinitionKey: TypeAlias = str | Literal['output_variables', 'signal_out', 'signal_error']

ConnectionKindV1: TypeAlias = Literal['file', 'queue', 'sql'] | str

ConnectionTypeV1: TypeAlias = Literal['clickhouse', 'ftp', 'kafka', 'mongodb', 'mssql', 'mysql', 'oracle', 'postgres', 's3', 'sftp', 'smbprotocol'] | str

class AIAnalysisCreateResponseSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    request_id: str = Field(...)
    status: AIAnalysisStatus = Field(...)

class AIAnalysisCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    task_id: str = Field(...)

class AIAnalysisHistoryItemSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    request_id: str = Field(...)
    project_id: str = Field(...)
    task_id: str | None = Field(...)
    status: AIAnalysisStatus = Field(...)
    title: str | None = Field(...)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    started_at: str | None = Field(...)
    finished_at: str | None = Field(...)
    error: str | None = Field(...)

class AIAnalysisHistoryResponseSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    items: list[AIAnalysisHistoryItemSchema] = Field(...)
    total: int = Field(...)
    limit: int = Field(...)
    offset: int = Field(...)

class AIAnalysisReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    request_id: str = Field(...)
    project_id: str = Field(...)
    status: AIAnalysisStatus = Field(...)
    title: str | None = Field(...)
    result: AIServiceAnalysisResultSchema | None = Field(...)
    error: str | None = Field(...)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    started_at: str | None = Field(...)
    finished_at: str | None = Field(...)

class AIServiceAnalysisResultSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    title: str = Field(...)
    classification: AIServiceAnalysisClassification = Field(...)
    severity: AIServiceAnalysisSeverity = Field(...)
    summary: str = Field(...)
    details: str = Field(...)
    recommended_actions: list[AIServiceRecommendedActionSchema] | None = Field(None)
    bug_report_suggested: bool | None = Field(False)
    matched_pattern: str | None = Field(None)
    source_context_used: list[AIServiceSourceContextItemSchema] | None = Field(None)

class AIServiceRecommendedActionSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    title: str = Field(...)
    description: str = Field(...)

class AIServiceSourceContextItemSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    path: str = Field(...)
    source: str = Field(...)
    snippet: str | None = Field(None)

class AdminUserCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    email: str = Field(...)
    user_name: str = Field(...)
    password: str = Field(...)
    role: DVTDefaultRoles | None = Field('user')
    organization_id: str | None = Field(None)

class AdminUserReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    external_id: str | None = Field(None)
    email: str = Field(...)
    password_version: int | None = Field(1)
    auth_provider: Literal['email', 'google', 'telegram'] = Field(...)
    user_name: str | None = Field(None)
    is_verified: bool | None = Field(False, description='User verification status')
    is_active: bool | None = Field(False, description='User account active status')
    role: DVTDefaultRoles | str | None = Field('user')
    signed_up_at: str | None = Field(None)
    last_password_change: str | None = Field(None)
    id: str | None = Field(None)
    organization_id: str = Field(..., description='ID организации пользователя')

class AdminUserUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    user_id: str = Field(...)
    email: str | None = Field(None)
    user_name: str | None = Field(None)
    password: str | None = Field(None)
    role: DVTDefaultRoles | None = Field(None)
    is_active: bool | None = Field(None)
    is_verified: bool | None = Field(None)
    organization_id: str | None = Field(None)

class AppSettingsDccReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    connector_id: str | None = Field(None, description='Connector ID')
    url: str | None = Field(None, description='DCC URL')
    username: str | None = Field(None, description='DCC User for auth')
    password: str | None = Field(None, description='DCC Password for auth')

class AppSettingsDccUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    connector_id: str | None = Field(None, description='Connector ID')
    url: str | None = Field(None, description='DCC URL')
    username: str | None = Field(None, description='DCC User for auth')
    password: str | None = Field(None, description='DCC Password for auth')

class AppSettingsLicenseReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    key: str | None = Field(None, description='License key')

class AppSettingsLicenseUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    key: str | None = Field(None, description='License key')

class AppSettingsRuntimeReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    oom_guard: OOMGuardConfig | None = Field(None, description='OOM guard policy settings configurable from UI')

class AppSettingsRuntimeUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    oom_guard: OOMGuardConfig | None = Field(None, description='OOM guard policy settings configurable from UI')

class AppSettingsReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dcc: AppSettingsDccReadSchema | None = Field(None)
    license: AppSettingsLicenseReadSchema | None = Field(None)
    runtime: AppSettingsRuntimeReadSchema | None = Field(None)

class AppSettingsUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dcc: AppSettingsDccUpdateSchema | None = Field(None)
    license: AppSettingsLicenseUpdateSchema | None = Field(None)
    runtime: AppSettingsRuntimeUpdateSchema | None = Field(None)

class AppSettingHistoryItemSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    key: str = Field(...)
    old_value: Any | None = Field(None)
    new_value: Any | None = Field(None)
    changed_at: str = Field(...)
    changed_by: str | None = Field(None)
    change_reason: str | None = Field(None)

class BaseModelSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)

class BaseVariableDefinitionModel(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: IO = Field(..., description='Тип базовой runtime-переменной')
    required: bool = Field(..., description='Обязательна ли базовая переменная в runtime')
    display_name: str | None = Field(None, description='Отображаемое имя базовой переменной')
    description: str | None = Field(None, description='Описание базовой переменной')

class BatchItem(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    key: str = Field(...)
    value: str = Field(...)

class BodyCreateFolderStorageFolderCreatePost(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    folder_name: str = Field(..., description='Name of the folder to create')
    path: str | None = Field('', description='Path prefix where to create the folder')

class BodyGetColumnsUtilsCsvGetColumnsPost(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(...)
    delimiter: str | None = Field(',')
    encoding: str | None = Field('utf-8')
    connection_id: str = Field(..., description='DBConnectionID')

class BodySqlCodeMetadataUtilsSqlCodeMetadataPost(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    sql_code: str = Field(...)
    connection_id: str = Field(..., description='DBConnectionID')

class BodyUploadFileViaGatewayStorageUploadFilePost(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str | None = Field('')
    file: str = Field(...)

class BrokenConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    state: Literal['invalid'] | None = Field('invalid')
    id: str = Field(...)
    name: str = Field(...)
    kind: str = Field(...)
    type: str = Field(...)
    driver: str | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    issues: list[ConnectionIssueResponse] | None = Field(None)
    raw_properties: Any | None = Field(None)
    raw_driver_options: Any | None = Field(None)
    raw_secrets: Any | None = Field(None)

class ClearProjectCacheRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    node_ids: list[str] | None = Field(None, description='List of node IDs to invalidate cache for')
    send_metadata_task: bool | None = Field(True, description='Whether or not to send a metadata inferring task to the worker')

class ClearProjectCacheResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    cleared_keys: list[str] | None = Field(None, description='List of cleared keys to invalidate metadata cache for')
    task_id: str | None = Field(None, description='ID of the task to invalidate metadata cache for')

class ClearProjectDataCacheRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    node_ids: list[str] | None = Field(None, description='List of node IDs to invalidate cache for')

class ClearProjectDataCacheResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    cleared_keys: list[str] | None = Field(None, description='List of cleared keys to invalidate metadata cache for')

class ClearProjectMetadataCacheRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    node_ids: list[str] | None = Field(None, description='List of node IDs to invalidate cache for')
    send_metadata_task: bool | None = Field(True, description='Whether or not to send a metadata inferring task to the worker')

class ClearProjectMetadataCacheResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    cleared_keys: list[str] | None = Field(None, description='List of cleared keys to invalidate metadata cache for')
    task_id: str | None = Field(None, description='ID of the task to invalidate metadata cache for')

class ClickHouseEngineSpec(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    engine_name: Literal['MergeTree', 'ReplacingMergeTree', 'SummingMergeTree', 'AggregatingMergeTree', 'CollapsingMergeTree', 'VersionedCollapsingMergeTree', 'ReplicatedMergeTree', 'ReplicatedReplacingMergeTree', 'ReplicatedSummingMergeTree', 'ReplicatedAggregatingMergeTree', 'ReplicatedCollapsingMergeTree', 'ReplicatedVersionedCollapsingMergeTree'] | None = Field('MergeTree')
    order_by: list[str] | None = Field(None)
    partition_by: list[str] | None = Field(None)
    primary_key: list[str] | None = Field(None)
    sample_by: list[str] | None = Field(None)
    ttl_expression: str | None = Field(None)
    version_column: str | None = Field(None)
    sign_column: str | None = Field(None)
    summing_columns: list[str] | None = Field(None)
    table_path: str | None = Field(None)
    replica_name: str | None = Field(None)
    settings: dict[str, str | int | float | bool] | None = Field(None)

class ClickhouseSqlHttpConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['clickhouse'] = Field(...)
    driver: Literal['http'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class ClickhouseSqlHttpConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['clickhouse'] = Field(...)
    driver: Literal['http'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class ClickhouseSqlHttpConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['http'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class ClickhouseSqlNativeDefaultDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['clickhouse'] = Field(...)
    driver: Literal['native'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class ClickhouseSqlNativeDefaultDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['clickhouse'] = Field(...)
    driver: Literal['native'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['native'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class Column(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя колонки в таблице.')
    dtype: DataType = Field(..., description='Тип данных колонки.')
    dtype_metadata: DTypeMetadata | None = Field(None, description='Метаданные типа данных колонки.')
    nullable: bool | None = Field(None, description='Флаг, указывающий, допускает ли колонка значения NULL.')
    index: bool | None = Field(None, description='Флаг, указывающий, участвует ли колонка в каком-либо индексе.')

class CommonResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')

class ConnectionCheckResult(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    connected: bool = Field(...)
    message: str | None = Field(None)
    exception: str | None = Field(None)

class ConnectionDriverInfoResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    options_schema: dict[str, Any] = Field(...)
    public_options_schema: dict[str, Any] | None = Field(None)
    tags: list[str] | None = Field(None)

class ConnectionIssueResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    field: str = Field(...)
    code: str = Field(...)
    message: str = Field(...)
    details: dict[str, Any] | None = Field(None)

class ConnectionKindInfoResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    description: str = Field(...)
    capabilities: list[str] | None = Field(None)

class ConnectionTypeInfoResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: str = Field(...)
    default_driver: str | None = Field(None)
    drivers: list[ConnectionDriverInfoResponse] | None = Field(None)
    supported_drivers: list[str] | None = Field(None)
    capabilities: list[str] | None = Field(None)
    tags: list[str] | None = Field(None)
    properties_schema: dict[str, Any] = Field(...)
    secrets_schema: dict[str, Any] | None = Field(None)
    public_schema: dict[str, Any] | None = Field(None)

class CreateDatabaseRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    connection_id: str = Field(...)
    database_name: str = Field(...)

class CreateSchemaRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    connection_id: str = Field(...)
    schema_name: str = Field(...)
    database_name: str | None = Field(None)

class CreateTableFromSQLRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    mode: Literal['from_sql'] | None = Field('from_sql')
    connection_id: str = Field(...)
    table_ddl: str = Field(...)
    database_name: str | None = Field(None)
    schema_name: str | None = Field(None)
    on_exists: Literal['ignore', 'recreate', 'error'] | None = Field('error')

class CreateTableFromSchemaRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    mode: Literal['from_schema'] | None = Field('from_schema')
    table_name: str = Field(...)
    connection_id: str = Field(...)
    database_name: str | None = Field(None)
    schema_name: str | None = Field(None)
    columns: list[DBColumn] = Field(...)
    table_create_spec: TableCreateSpec | None = Field(None)
    on_exists: Literal['ignore', 'recreate', 'error'] | None = Field('error')

class DBColumn(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя колонки в таблице.')
    dtype: DataType = Field(..., description='Тип данных колонки.')
    dtype_metadata: DTypeMetadata | None = Field(None, description='Метаданные типа данных колонки.')
    nullable: bool | None = Field(None, description='Флаг, указывающий, допускает ли колонка значения NULL.')
    index: bool | None = Field(None, description='Флаг, указывающий, участвует ли колонка в каком-либо индексе.')
    indexes: list[str] | None = Field(None, description='Список индексов, в которых участвует колонка (с указанием типа индекса).')
    primary_key: bool | None = Field(None, description='Флаг, указывающий, является ли колонка частью PRIMARY KEY.')

class DBDatabase(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя базы данных.')
    schemas: list[DBSchema] | None = Field(None, description='Схемы базы данных.')
    tables: list[DBTable] | None = Field(None, description='Таблицы базы данных для диалектов без слоя схем.')

class DBMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['DATABASE'] | None = Field('DATABASE')
    dialect: Literal['postgresql', 'mysql', 'mariadb', 'mongodb', 'mssql', 'sqlserver', 'clickhouse', 'sqlite', 'oracle'] | str = Field(..., description='Диалект базы данных')
    databases: list[DBDatabase] | None = Field(None, description='Список баз данных.')
    schemas: list[DBSchema] | None = Field(None, description='Список схем в соединении.')
    tables: list[DBTable] | None = Field(None, description='Список таблиц в корне метаданных.')
    database_name: str | None = Field(None, description='Имя базы данных.')
    connection_string: str | None = Field(None, description='Строка подключения к базе данных (без учетных данных).')

class DBSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя схемы.')
    database_name: str | None = Field(None, description='Имя базы данных, к которой относится схема (если применимо).')
    tables: list[DBTable] | None = Field(None, description='Список таблиц и представлений в схеме.')

class DBTable(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str | None = Field(None, description='Уникальный идентификатор таблицы.')
    schema_name: str | None = Field(None, description='Схема, которой принадлежит таблица (если применимо).')
    database_name: str | None = Field(None, description='Имя базы данных, к которой принадлежит таблица (если применимо).')
    name: str = Field(..., description='Имя таблицы в базе данных.')
    columns: list[DBColumn] = Field(..., description='Список колонок в таблице.')
    type: DBTableType = Field(..., description='Тип таблицы (например, BASE TABLE, VIEW).')

class DTypeMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя типа данных.')
    class_: str = Field(..., alias='class', description='Класс типа данных.')
    origin: Literal['numpy', 'pandas', 'python'] = Field(..., description='Источник типа данных.')
    repr: str | None = Field(None, description='Строковое представление dtype.')
    module: str | None = Field(None, description='Полное имя Python-модуля класса dtype.')
    kind: str | None = Field(None, description='Низкоуровневый код kind для dtype.')
    itemsize: int | None = Field(None, description='Размер элемента dtype в байтах, если применимо.')
    is_extension: bool | None = Field(None, description='Является ли dtype pandas ExtensionDtype.')
    scalar_type: str | None = Field(None, description='Имя скалярного типа элементов dtype.')
    storage: str | None = Field(None, description='Бэкенд хранения dtype, если он задан.')
    unit: str | None = Field(None, description='Единица времени для datetime/timedelta dtype.')
    timezone: str | None = Field(None, description='Часовой пояс для timezone-aware datetime dtype.')
    ordered: bool | None = Field(None, description='Флаг упорядоченности категориального dtype.')
    categories_count: int | None = Field(None, description='Количество категорий для category dtype.')
    categories_dtype: str | None = Field(None, description='dtype значений категорий для category dtype.')

class DataFrameData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    columns: list[Column] = Field(..., description='Колонки DataFrame')
    values: list[list[Any]] = Field(..., description='Данные DataFrame как список списков')
    total_rows: int = Field(..., description='Количество строк в DataFrame')
    total_partitions: int = Field(..., description='Количество партиций в DataFrame')

class DataFrameMetadataInput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['DATAFRAME'] | None = Field('DATAFRAME')
    columns: list[Column] = Field(...)
    rows_num: int | None = Field(None)
    size: int | None = Field(None, description='Размер DataFrame в байтах')

class DataFrameMetadataOutput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['DATAFRAME'] | None = Field('DATAFRAME')
    columns: list[Column] = Field(...)
    rows_num: int | None = Field(None)
    size: int | None = Field(None, description='Размер DataFrame в байтах')

class DeleteFilesIn(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    paths: list[str] = Field(...)

class DeleteFolderIn(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(...)

class EnvironmentFilterDefinition(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Name of environment filter')
    expression: str = Field(..., description='Expression of environment filter')
    description: str | None = Field(None, description='Description of environment filter')

class EnvironmentGlobalDefinition(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Name of environment global')
    expression: str = Field(..., description='Expression of environment global')
    description: str | None = Field(None, description='Description of environment global')

class EnvironmentTestDefinition(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Name of environment test')
    expression: str = Field(..., description='Expression of environment test')
    description: str | None = Field(None, description='Description of environment test')

class ErrorResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    code: str = Field(..., description='Код ошибки')
    detail: str = Field(..., description='Описание ошибки')

class ExpressionPolicy(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    allowed_filters: list[str] = Field(...)
    allowed_globals: list[str] | None = Field([])
    allowed_tests: list[str] | None = Field([])
    allow_statements: bool | None = Field(False)
    allow_comments: bool | None = Field(True)

class ExpressionsConfig(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    filters: list[EnvironmentFilterDefinition] | None = Field(None)
    tests: list[EnvironmentTestDefinition] | None = Field(None)
    globals: list[EnvironmentGlobalDefinition] | None = Field(None)
    default_policy: ExpressionPolicy = Field(...)

class ExtensionFrontendReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    extension_name: str = Field(...)
    installed: bool = Field(...)
    bundle_url: str = Field(...)
    entry_file: str = Field(...)
    entrypoint: str | None = Field(None)

class ExtensionManifestBackendSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    nodes_dir: str | None = Field('backend/nodes')

class ExtensionManifestFrontendSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dist_dir: str | None = Field('frontend/dist')
    entry_file: str | None = Field('index.js')
    entrypoint: str | None = Field(None)

class ExtensionManifestNodeSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    display_name: str = Field(...)
    description: str | None = Field('')

class ExtensionManifestSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('')
    version: str | None = Field('')
    dvt_version: str | None = Field(None)
    display_name: str | None = Field(None)
    description: str | None = Field('')
    repository_url: str | None = Field(None)
    homepage_url: str | None = Field(None)
    required_license: str | None = Field(None)
    backend: ExtensionManifestBackendSchema | None = Field(None)
    frontend: ExtensionManifestFrontendSchema | None = Field(None)
    requirements: list[str] | None = Field(None)
    state_schema: dict[str, Any] | None = Field(None)
    nodes: list[ExtensionManifestNodeSchema] | None = Field(None)

class ExtensionReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str | None = Field(None)
    name: str = Field(...)
    display_name: str = Field(...)
    description: str | None = Field('')
    repository_url: str | None = Field(None)
    is_enabled: bool = Field(...)
    is_installed: bool = Field(...)
    deps_status: ExtensionDepsStatus | None = Field('not_installed')
    current_version: str | None = Field(None)
    last_version: str | None = Field(None)
    install_path: str | None = Field(None)
    manifest_json: ExtensionManifestSchema | None = Field(None)
    state_json: dict[str, Any] | None = Field(None)
    available_versions: list[str] | None = Field(None)
    error_message: str | None = Field(None)
    installed_at: str | None = Field(None)
    created_at: str | None = Field(None)
    updated_at: str | None = Field(None)
    license_status: ExtensionLicenseStatus | None = Field(None)
    license_activated_at: str | None = Field(None)
    license_expires_at: str | None = Field(None)

class ExtensionStateReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    extension_name: str = Field(...)
    state_key: str | None = Field('default')
    value: dict[str, Any] | None = Field(None)

class ExtensionStateUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    value: dict[str, Any] | None = Field(None)

class FTPFile(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['file'] | None = Field('file')
    name: str = Field(..., description='Имя узла (название файла или папки)')
    path: str = Field(..., description='Полный путь к узлу')
    size: int = Field(..., description='Размер файла в байтах')
    last_modified: str | None = Field(None, description='Дата последнего изменения')
    permissions: str | None = Field(None, description='Права доступа (например, 644 или -rw-r--r--)')

class FTPFolder(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['folder'] | None = Field('folder')
    name: str = Field(..., description='Имя узла (название файла или папки)')
    path: str = Field(..., description='Полный путь к узлу')
    permissions: str | None = Field(None, description='Права доступа (например, 755 или drwxr-xr-x)')

class FTPProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    host: str = Field(..., description='FTP server hostname or IP address')
    port: int | None = Field(21, description='FTP server port')
    mode: FTPMode | None = Field('ftp', description='Connection mode')
    username: str | None = Field(None, description='Username for authentication')
    anonymous: bool | None = Field(False, description='Use anonymous login')
    encoding: str | None = Field('utf-8', description='Connection encoding')
    initial_directory: str | None = Field(None, description='Initial directory after login')
    ssl_context: dict[str, Any] | None = Field(None, description='Custom SSL context config')
    verify_ssl: bool | None = Field(True, description='Verify SSL certificates')
    certfile: str | None = Field(None, description='Client certificate file')
    keyfile: str | None = Field(None, description='Client private key file')

class FTPSecrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    password: str | None = Field(None)

class ForeignKeySpec(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    columns: list[str] = Field(...)
    ref_table: str = Field(...)
    ref_schema: str | None = Field(None)
    ref_columns: list[str] = Field(...)

class FtpFileNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['ftp'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: FTPProperties = Field(...)
    secrets: FTPSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class FtpFileNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['ftp'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: FTPProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class FtpFileNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: FTPProperties | None = Field(None)
    secrets: FTPSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class GenerateSchemaDDLRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    connection_id: str = Field(...)
    schema_name: str = Field(...)
    database_name: str | None = Field(None)

class GenerateSchemaDDLResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    sql: str = Field(...)

class GenerateTableDDL(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dataframe_metadata: DataFrameMetadataInput | None = Field(None)
    connection_id: str = Field(...)
    table_name: str = Field(...)
    database_name: str | None = Field(None)
    schema_name: str | None = Field(None)
    index_col: str | list[str] | None = Field(None)
    columns: list[DBColumn] | None = Field(None)
    table_create_spec: TableCreateSpec | None = Field(None)

class GenerateTableDDLResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    sql: str = Field(...)

class GraphEdgeUISchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    type: str = Field(...)
    subgraphid: str | None = Field(None, alias='subgraphId')
    source: str = Field(...)
    sourcehandle: str | None = Field(None, alias='sourceHandle', description='Handle ID on the source edge for this edge')
    target: str = Field(...)
    targethandle: str | None = Field(None, alias='targetHandle', description='Handle ID on the target edge for this edge')

class GraphEdgeUpdateUISchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str | None = Field(None)
    type: str | None = Field(None)
    subgraphid: str | None = Field(None, alias='subgraphId')
    source: str | None = Field(None)
    sourcehandle: str | None = Field(None, alias='sourceHandle', description='Handle ID on the source edge for this edge')
    target: str | None = Field(None)
    targethandle: str | None = Field(None, alias='targetHandle', description='Handle ID on the target edge for this edge')

class GraphNodeData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    displayname: str = Field(..., alias='displayName')
    storeenabled: bool | None = Field(False, alias='storeEnabled')
    showsignalio: bool | None = Field(False, alias='showSignalIo')
    showvariablesio: bool | None = Field(False, alias='showVariablesIo')
    comment: str | None = Field(None)
    inputvalues: dict[str, NodeInputExpressionValue | NodeInputConstantValue | NodeInputLinkValue] | None = Field(None, alias='inputValues')

class GraphNodeDataUpdate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    displayname: str | None = Field(None, alias='displayName')
    storeenabled: bool | None = Field(None, alias='storeEnabled')
    showsignalio: bool | None = Field(None, alias='showSignalIo')
    showvariablesio: bool | None = Field(None, alias='showVariablesIo')
    comment: str | None = Field(None)
    inputvalues: dict[str, NodeInputExpressionValue | NodeInputConstantValue | NodeInputLinkValue] | None = Field(None, alias='inputValues')

class GraphNodeUISchemaInput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    type: str = Field(...)
    subgraphid: str | None = Field(None, alias='subgraphId')
    position: Position = Field(...)
    selected: bool | None = Field(False)
    data: GraphNodeData = Field(...)

class GraphNodeUISchemaOutput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    type: str = Field(...)
    subgraphid: str | None = Field(None, alias='subgraphId')
    position: Position = Field(...)
    selected: bool | None = Field(False)
    data: GraphNodeData = Field(...)

class GraphNodeUIUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    data: GraphNodeDataUpdate | None = Field(None)
    type: str | None = Field(None)
    subgraphid: str | None = Field(None, alias='subgraphId')
    position: Position | None = Field(None)
    selected: bool | None = Field(None)

class GraphOperationResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    nodes_deleted: list[str] | None = Field([])
    nodes_created: list[str] | None = Field([])
    nodes_updated: list[str] | None = Field([])
    edges_deleted: list[str] | None = Field([])
    edges_created: list[str] | None = Field([])
    edges_updated: list[str] | None = Field([])
    subgraphs_deleted: list[str] | None = Field([])
    subgraphs_created: list[str] | None = Field([])
    subgraphs_updated: list[str] | None = Field([])
    task_id: str | None = Field(None)

class GraphOperationsAggregated(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    nodes_to_delete: list[BaseModelSchema] | None = Field([])
    nodes_to_create: list[GraphNodeUISchemaInput] | None = Field([])
    nodes_to_update: list[GraphNodeUIUpdateSchema] | None = Field([])
    edges_to_delete: list[BaseModelSchema] | None = Field([])
    edges_to_create: list[GraphEdgeUISchema] | None = Field([])
    edges_to_update: list[GraphEdgeUpdateUISchema] | None = Field([])
    subgraphs_to_delete: list[BaseModelSchema] | None = Field([])
    subgraphs_to_create: list[SubgraphUISchema] | None = Field([])
    subgraphs_to_update: list[SubgraphUIUpdateSchema] | None = Field([])

class HTTPValidationError(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    detail: list[ValidationError] | None = Field(None)

class IndexSpec(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    columns: list[str] = Field(...)
    unique: bool | None = Field(False)

class InputDefinitionModel(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    attr_name: str | Literal['input_variables', 'signal_in'] = Field(..., description='Имя атрибута в классе Python')
    display_name: str | None = Field(None, description='Отображаемое имя (для UI)')
    type: IO | list[IO] = Field(..., description='Строковое представление типа ComfyUI')
    display_type: str | None = Field(None, description='Отображаемый тип (для UI)')
    is_list_type: bool = Field(..., description='Является ли тип списком')
    is_literal_type: bool = Field(..., description='Является ли тип выбором (COMBO)')
    options: list[str] | None = Field(None, description='Возможные значения (для выбора)')
    optional: bool = Field(..., description='Является ли поле опциональным')
    is_hidden: bool = Field(..., description='Является ли поле скрытым')
    description: str | None = Field(None, description='Описание поля')
    default: Any | None = Field(None, description='Значение по умолчанию')
    multiline: bool | None = Field(None, description='Подсказка UI: многострочный ввод')
    metadata_source_field: str | None = Field(None, description='Названия поля для источника метаданных')
    min_value: int | float | None = Field(None, description='Минимальное значение (для чисел)')
    max_value: int | float | None = Field(None, description='Максимальное значение (для чисел)')
    step: int | float | None = Field(None, description='Шаг (для чисел)')
    round_val: int | float | None = Field(None, description='Округление (для чисел)')
    schema: dict[str, Any] | None = Field(None, description='Дополнительная схема для виджета')
    allow_multiple_connections: bool | None = Field(False, description='Разрешить множественные подключения')
    allow_new: bool | None = Field(False, description='Разрешить новые имена колонок (только для "IO.COLUMN_NAME"')
    allow_expressions: bool | None = Field(True, description='Разрешены ли вычисляемые значения')
    expression_policy: str | None = Field(None, description='Имя политики sandbox для выражений')
    force_handle_visible: bool | None = Field(False, description='Всегда показывать handle')
    use_widget: bool | None = Field(None, description='Переопределение использование виджета')
    use_connection: bool | None = Field(None, description='Переопределение использование коннекта')

class JSONData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    data: Any = Field(..., description='JSON payload (dict/list/primitive)')
    total_items: int | None = Field(None, description='Total items count if payload is a list, otherwise None')

class KafkaProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    bootstrap_servers: list[str] = Field(...)
    security_protocol: str | None = Field('PLAINTEXT')
    sasl_mechanism: str | None = Field(None)
    sasl_plain_username: str | None = Field(None)
    client_id: str | None = Field('kafka_client')
    request_timeout_ms: int | None = Field(30000)

class KafkaQueueNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['queue'] = Field(...)
    type: Literal['kafka'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: KafkaProperties = Field(...)
    secrets: KafkaSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class KafkaQueueNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['queue'] = Field(...)
    type: Literal['kafka'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: KafkaProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class KafkaQueueNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: KafkaProperties | None = Field(None)
    secrets: KafkaSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class KafkaSecrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    sasl_plain_password: str | None = Field(None)

class LicenseActivationSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    license_key: str = Field(...)

class LicenseStatusSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    extension_name: str = Field(...)
    license_status: str | None = Field(...)
    license_key: str | None = Field(...)
    license_activated_at: str | None = Field(...)
    license_expires_at: str | None = Field(...)
    required_license: str | None = Field(...)

class LogEntriesPageSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    items: list[LogEntrySchema] | None = Field(None, description='Страница логов')
    total: int = Field(..., description='Общее количество логов')
    limit: int = Field(..., description='Размер страницы')
    offset: int = Field(..., description='Смещение страницы')
    has_more: bool = Field(..., description='Есть ли следующая страница')

class LogEntrySchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    created_at: str = Field(..., description='Время создания записи')
    level: str = Field(..., description='Уровень лога (INFO, DEBUG, etc.)')
    service_name: str = Field(..., description='Имя сервиса, сгенерировавшего лог')
    message: str = Field(..., description='Текст сообщения')
    exception_traceback: str | None = Field(None, description='Трассировка исключения, если есть')
    logger_name: str | None = Field(None, description='Имя логгера (record.name)')
    module: str | None = Field(None, description='Модуль, откуда пришёл лог')
    function: str | None = Field(None, description='Функция')
    line: int | None = Field(None, description='Номер строки')

class MongodbSqlNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mongodb'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MongodbSqlNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mongodb'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class MongodbSqlNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MSSQLNamedInstanceProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    host: str = Field(...)
    instance_name: str = Field(...)
    username: str = Field(...)
    database: str = Field(...)
    secure: bool | None = Field(False)
    connect_timeout: int | None = Field(30)
    send_receive_timeout: int | None = Field(60)
    sync_request_timeout: int | None = Field(60)
    ca_cert_string: str | None = Field(None)
    verify: bool | None = Field(False)

class MSSQLTCPProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    host: str = Field(...)
    port: int = Field(...)
    username: str = Field(...)
    database: str = Field(...)
    secure: bool | None = Field(False)
    connect_timeout: int | None = Field(30)
    send_receive_timeout: int | None = Field(60)
    sync_request_timeout: int | None = Field(60)
    ca_cert_string: str | None = Field(None)
    verify: bool | None = Field(False)

MSSQLProperties: TypeAlias = MSSQLTCPProperties | MSSQLNamedInstanceProperties

class MovePathIn(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(...)
    target_path: str | None = Field('')

class MssqlSqlAioodbcConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mssql'] = Field(...)
    driver: Literal['aioodbc'] = Field(...)
    driver_options: ODBCDriverOptionsInput = Field(...)
    properties: MSSQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MssqlSqlAioodbcConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mssql'] = Field(...)
    driver: Literal['aioodbc'] = Field(...)
    driver_options: ODBCDriverOptionsOutput = Field(...)
    properties: MSSQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class MssqlSqlAioodbcConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['aioodbc'] = Field(...)
    driver_options: ODBCDriverOptionsInput | None = Field(None)
    properties: MSSQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MssqlSqlPyodbcDefaultDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mssql'] = Field(...)
    driver: Literal['pyodbc'] | None = Field(None)
    driver_options: ODBCDriverOptionsInput = Field(...)
    properties: MSSQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MssqlSqlPyodbcDefaultDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mssql'] = Field(...)
    driver: Literal['pyodbc'] | None = Field(None)
    driver_options: ODBCDriverOptionsOutput = Field(...)
    properties: MSSQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['pyodbc'] | None = Field(None)
    driver_options: ODBCDriverOptionsInput | None = Field(None)
    properties: MSSQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MysqlSqlAiomysqlConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mysql'] = Field(...)
    driver: Literal['aiomysql'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MysqlSqlAiomysqlConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mysql'] = Field(...)
    driver: Literal['aiomysql'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class MysqlSqlAiomysqlConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['aiomysql'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MysqlSqlPymysqlDefaultDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mysql'] = Field(...)
    driver: Literal['pymysql'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class MysqlSqlPymysqlDefaultDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['mysql'] = Field(...)
    driver: Literal['pymysql'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['pymysql'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class NodeDefinition(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    input_definitions: dict[str, InputDefinitionModel] = Field(..., description='Mapping определений входных полей по attr_name')
    output_definitions: dict[str, OutputDefinitionModel] = Field(..., description='Mapping определений выходных полей по attr_name')
    system_variable_definitions: dict[str, SystemVariableDefinitionModel] | None = Field(None, description='Mapping определений системных переменных по имени переменной')
    name: str = Field(..., description='Имя класса ноды (уникальный идентификатор)')
    emoji: str | None = Field(None, description='Эмодзи иконка для ноды')
    display_name: str = Field(..., description='Отображаемое имя ноды')
    description: str | None = Field('', description='Описание ноды')
    python_module: str = Field(..., description='Относительный путь к Python модулю ноды')
    category: str = Field(..., description='Категория ноды для группировки')
    category_color: str = Field(..., description='Hex-цвет категории ноды для UI')
    tags: list[str] = Field(..., description='Список тегов ноды')
    type: NodeType = Field(..., description='Типы ноды')
    output_node: bool = Field(..., description='Является ли нода выходной (конечной точкой)')
    deprecated: bool | None = Field(False, description='Является ли нода устаревшей')
    experimental: bool | None = Field(False, description='Является ли нода экспериментальной')
    visible: bool | None = Field(True, description='Является ли нода видимой')
    additional_schema: dict[str, Any] | None = Field(None, description='')
    extension_name: str | None = Field(None, description='Имя пакета-расширения')
    extension_version: str | None = Field(None, description='Версия пакета-расширения')

class NodeInputConstantValue(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dvt_type: Literal['const'] | None = Field('const', alias='__dvt_type')
    value: Any = Field(..., description='Значение константы')

class NodeInputExpressionValue(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dvt_type: Literal['expr'] | None = Field('expr', alias='__dvt_type')
    value: str = Field(..., description='Текст вычисляемого выражения')
    expression_kind: Literal['single', 'template'] = Field(..., description='Тип выражения: одиночное выражение или шаблон')

class NodeInputLinkValue(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    dvt_type: Literal['link'] | None = Field('link', alias='__dvt_type')
    node_id: str = Field(..., description='ID ноды-источника')
    output_name: str = Field(..., description='Имя выходного поля ноды-источника')

class ODBCDriverOptionsInput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    driver_name: str = Field(...)

class ODBCDriverOptionsOutput(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    odbc_driver_name: str = Field(...)

class OOMGuardConfig(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    mode: OOMGuardMode | None = Field('DISABLED')
    host_threshold_percent: float | None = Field(None)
    worker_threshold_type: OOMWorkerThresholdType | None = Field(None)
    worker_threshold_percent: float | None = Field(None)
    worker_threshold_mb: int | None = Field(None)

class OracleSqlOracledbDefaultDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['oracle'] = Field(...)
    driver: Literal['oracledb'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class OracleSqlOracledbDefaultDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['oracle'] = Field(...)
    driver: Literal['oracledb'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class OracleSqlOracledbDefaultDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['oracledb'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class OrganizationCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Organization name')
    description: str | None = Field(None, description='Organization description')
    inn: str | None = Field(None, description='Organization INN')
    is_active: bool | None = Field(True, description='Is organization active')

class OrganizationReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    projects_count: int | None = Field(0)
    created_at: str | None = Field(None, description='Timestamp when the record was created')
    updated_at: str | None = Field(None, description='Timestamp when the record was last updated')
    id: str | None = Field(None)
    name: str = Field(..., description='Organization name')
    description: str | None = Field(None, description='Organization description')
    inn: str | None = Field(None, description='Organization INN')
    is_active: bool | None = Field(True, description='Is organization active')

class OrganizationUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None, description='Organization name')
    description: str | None = Field(None, description='Organization description')
    inn: str | None = Field(None, description='Organization INN')
    is_active: bool | None = Field(None, description='Is organization active')

class OutputDefinitionModel(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    attr_name: str | Literal['output_variables', 'signal_out', 'signal_error'] = Field(..., description='Имя атрибута в классе Python')
    display_name: str | None = Field(None, description='Отображаемое имя (для UI)')
    type: IO | list[IO] = Field(..., description='Строковое представление типа ComfyUI')
    display_type: str | None = Field(None, description='Отображаемый тип (для UI)')
    is_list_type: bool = Field(..., description='Является ли тип списком')
    description: str | None = Field(None, description='Описание поля')
    tooltip: str | None = Field(None, description='Подсказка для выхода')
    force_handle_visible: bool | None = Field(False, description='Всегда показывать handle')

class Position(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    x: float = Field(...)
    y: float = Field(...)

class PostgresSqlAsyncpgConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['asyncpg'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PostgresSqlAsyncpgConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['asyncpg'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class PostgresSqlAsyncpgConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['asyncpg'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopg2ConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['psycopg2'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopg2ConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['psycopg2'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopg2ConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['psycopg2'] = Field(...)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopgDefaultDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['psycopg'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopgDefaultDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['sql'] = Field(...)
    type: Literal['postgres'] = Field(...)
    driver: Literal['psycopg'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: Literal['psycopg'] | None = Field(None)
    driver_options: NoDriverOptions | None = Field(None)
    properties: SQLProperties | None = Field(None)
    secrets: SQLSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class PresignedPostOut(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    url: str = Field(...)
    fields: dict[str, str] = Field(...)

class ProjectCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    folder_id: str | None = Field(None, description='ID папки проекта')
    variables: dict[str, ProjectVariableBase] | None = Field(None, description='Typed-переменные проекта')
    name: str = Field(..., description='Name of the project')
    store_enabled: bool | None = Field(False, description='Включен ли кеш данных для этого проекта')
    ttl_time: int | None = Field(0, description='Время жизни кеша данных в секундах')
    workers_count: int | None = Field(0, description='Количество потоков для подключений')

class ProjectFolderCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Название папки проектов')
    parent_id: str | None = Field(None, description='ID родительской папки')

class ProjectFolderItemSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['folder', 'project'] = Field(..., description='Тип элемента')
    folder: ProjectFolderReadSchema | None = Field(None, description='Данные папки')
    project: ProjectReadSchema | None = Field(None, description='Данные проекта')

class ProjectFolderReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(..., description='ID папки проектов')
    name: str = Field(..., description='Название папки проектов')
    parent_id: str | None = Field(None, description='ID родительской папки')
    user_id: str = Field(..., description='ID владельца папки')
    user_email: str | None = Field(None, description='Email владельца папки')
    organization_id: str = Field(..., description='ID организации')
    is_deleted: bool | None = Field(False, description='Удалена ли папка')
    created_at: str = Field(..., description='Дата создания')
    updated_at: str = Field(..., description='Дата обновления')

class ProjectFolderUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None, description='Новое название папки проектов')
    parent_id: str | None = Field(None, description='Новый ID родительской папки')

class ProjectItemsPageSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    items: list[ProjectFolderItemSchema] | None = Field(None, description='Элементы папки')
    total: int = Field(..., description='Общее количество элементов')
    limit: int = Field(..., description='Размер страницы')
    offset: int = Field(..., description='Смещение страницы')
    has_more: bool = Field(..., description='Есть ли следующая страница')
    folder_id: str | None = Field(None, description='ID текущей папки')

class ProjectLastRunSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    task_id: str = Field(..., description='ID запуска проекта')
    status: TaskStatus = Field(..., description='Статус запуска проекта')
    queued_at: str = Field(..., description='Время постановки запуска в очередь')
    started_at: str | None = Field(None, description='Время начала запуска проекта')
    finished_at: str | None = Field(None, description='Время завершения запуска проекта')
    message: str | None = Field(None, description='Краткое сообщение о результате запуска')
    termination_reason: str | None = Field(None, description='Причина аварийного завершения запуска')

class ProjectReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    folder_id: str | None = Field(None, description='ID папки проекта')
    user_email: str | None = Field(None, description='Email владельца проекта')
    variables: dict[str, ProjectVariableBase] | None = Field(None, description='Typed-переменные проекта')
    last_runs: list[ProjectLastRunSchema] | None = Field(None, description='Последние scheduler-запуски проекта')
    created_at: str | None = Field(None, description='Timestamp when the record was created')
    updated_at: str | None = Field(None, description='Timestamp when the record was last updated')
    name: str = Field(..., description='Name of the project')
    organization_id: str = Field(..., description='ID организации, которой принадлежит проект')
    is_deleted: bool | None = Field(False, description='Flag indicating if the project is deleted')
    store_enabled: bool | None = Field(False, description='Включен ли кеш данных для этого проекта')
    ttl_time: int | None = Field(0, description='Время жизни кеша данных в секундах')
    workers_count: int | None = Field(0, description='Количество потоков для подключений')

class ProjectSchedulePatchRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    cron: str | None = Field(None, description='Новое выражение CRON для расписания проекта')
    scheduled_by_user_id: str | None = Field(None, description='ID пользователя, который последним сохранил расписание')
    mode: PipelineExecutionMode | None = Field(None, description='Новый режим выполнения задачи')
    force_exec: bool | None = Field(None, description='Новое значение принудительного выполнения')
    disabled: bool | None = Field(None, description='Новое состояние расписания')

class ProjectScheduleRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    project_id: str = Field(..., description='ID проекта')
    mode: PipelineExecutionMode | None = Field('full', description='Режим выполнения задачи')
    force_exec: bool | None = Field(False, description='Принудительное выполнение')
    cron: str = Field(..., description='Выражение CRON для планирования проекта')

class ProjectScheduleResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    project_id: str = Field(..., description='ID проекта')
    mode: PipelineExecutionMode | None = Field('full', description='Режим выполнения задачи')
    force_exec: bool | None = Field(False, description='Принудительное выполнение')
    cron: str = Field(..., description='Выражение CRON для планирования проекта')
    disabled: bool | None = Field(False, description='Отключено ли расписание')
    scheduled_by_user_id: str | None = Field(None, description='ID пользователя, который последним сохранил расписание')
    task_id: str | None = Field(None, description='ID задачи в планировщике')
    next_run_time: str | None = Field(None, description='Время следующего запуска')
    last_run_time: str | None = Field(None, description='Время последнего запуска проекта')
    last_run_status: TaskStatus | None = Field(None, description='Статус последнего запуска проекта')
    last_run_task_id: str | None = Field(None, description='ID последнего запуска проекта')
    last_run_message: str | None = Field(None, description='Сообщение последнего запуска проекта')
    last_run_termination_reason: str | None = Field(None, description='Причина аварийного завершения последнего запуска проекта')
    recent_runs: list[ProjectScheduleRunResponse] | None = Field(None, description='История последних scheduler-запусков проекта')

class ProjectScheduleRunResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    task_id: str = Field(..., description='ID запуска проекта')
    status: TaskStatus = Field(..., description='Статус запуска проекта')
    queued_at: str = Field(..., description='Время постановки запуска в очередь')
    started_at: str | None = Field(None, description='Время начала запуска проекта')
    finished_at: str | None = Field(None, description='Время завершения запуска проекта')
    message: str | None = Field(None, description='Краткое сообщение о результате запуска')
    termination_reason: str | None = Field(None, description='Причина аварийного завершения запуска')

class ProjectSearchPageSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    items: list[ProjectFolderItemSchema] | None = Field(None, description='Найденные папки и проекты')
    total: int = Field(..., description='Общее количество найденных элементов')
    limit: int = Field(..., description='Размер страницы')
    offset: int = Field(..., description='Смещение страницы')
    has_more: bool = Field(..., description='Есть ли следующая страница')

class ProjectUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    folder_id: str | None = Field(None, description='ID папки проекта')
    variables: dict[str, ProjectVariableBase] | None = Field(None, description='Typed-переменные проекта')
    name: str | None = Field(None, description='Name of the project')
    store_enabled: bool | None = Field(None, description='Включен ли кеш данных для этого проекта')
    ttl_time: int | None = Field(None, description='Время жизни кеша данных в секундах')
    workers_count: int | None = Field(None, description='Количество потоков для подключений')

class ProjectVariableBase(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DATETIME', 'TIMEDELTA', 'JSON'] = Field(..., description='Тип переменной')
    value: Any = Field(..., description='Значение переменной')
    is_list_type: bool | None = Field(False, description='Является ли переменная списком')

class ProjectVariableCreate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DATETIME', 'TIMEDELTA', 'JSON'] = Field(..., description='Тип переменной')
    value: Any = Field(..., description='Значение переменной')
    is_list_type: bool | None = Field(False, description='Является ли переменная списком')

class ProjectVariableRead(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DATETIME', 'TIMEDELTA', 'JSON'] = Field(..., description='Тип переменной')
    value: Any = Field(..., description='Значение переменной')
    is_list_type: bool | None = Field(False, description='Является ли переменная списком')
    key: str = Field(..., description='Ключ переменной')

class ProjectVariableUpdate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DATETIME', 'TIMEDELTA', 'JSON'] = Field(..., description='Тип переменной')
    value: Any = Field(..., description='Значение переменной')
    is_list_type: bool | None = Field(False, description='Является ли переменная списком')

class ProjectVariablesBulkUpdate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    variables: dict[str, ProjectVariableBase] = Field(..., description='Словарь typed-переменных для обновления')

class ProjectsDeleteSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    project_ids: list[str] = Field(..., description='Список ID проектов для удаления')

class PytestEntityListResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    root_path: str = Field(...)
    fingerprint: str = Field(...)
    count: int = Field(...)
    items: list[PytestEntitySchema] | None = Field(None)
    errors: list[str] | None = Field(None)

class PytestEntityLocation(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    absolute_path: str = Field(...)
    relative_path: str = Field(...)
    lineno: int = Field(...)
    end_lineno: int = Field(...)

class PytestEntitySchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    python_name: str = Field(...)
    qualified_name: str = Field(...)
    signature: str = Field(...)
    description: str | None = Field(None)
    code: str = Field(...)
    is_async: bool = Field(...)
    location: PytestEntityLocation = Field(...)

class QueueActionRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    action: QueueAction = Field(..., description='Queue action to perform')
    task_id: str = Field(..., description='Task identifier to apply the action to')

class QueueActionResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    task_id: str = Field(..., description='Task identifier the action was applied to')

class QueueStateResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    tasks: list[QueueTask] | None = Field(None, description='List of pending tasks')

class QueueTask(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    task_id: str = Field(..., description='Task identifier')
    project_id: str = Field(..., description='Related project identifier')
    mode: PipelineExecutionMode = Field(..., description='Execution mode')
    force_exec: bool | None = Field(False, description='Whether the task was forced to execute')
    queued_at: str = Field(..., description='Timestamp when task was enqueued')
    status: TaskStatus = Field(..., description='Current status of the task')
    termination_reason: str | None = Field(None, description='Reason for task termination if applicable')
    assigned_worker_id: str | None = Field(None, description='Identifier of the worker assigned to the task')
    source: TaskSource = Field(..., description='Task source')
    started_at: str | None = Field(None, description='Timestamp when task was started')
    finished_at: str | None = Field(None, description='Timestamp when task was finished')
    message: str | None = Field(None, description='Task message')

class QueueTopicCreateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Name of the topic')
    columns_schema: list[Column] = Field(..., description="Data's schema of the topic")

class QueueTopicDataSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    data: list[dict[str, Any]] = Field(...)

class QueueTopicDataSuccessSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(...)
    message: str = Field(...)
    stored_count: int = Field(...)

class QueueTopicReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    created_at: str | None = Field(None, description='Timestamp when the record was created')
    updated_at: str | None = Field(None, description='Timestamp when the record was last updated')
    id: str | None = Field(None)
    name: str = Field(..., description='Name of the topic')
    columns_schema: list[Column] = Field(..., description="Data's schema of the topic")

class QueueTopicUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None, description='Name of the topic')
    columns_schema: list[Column] | None = Field(None, description="Data's schema of the topic")

class RenamePathIn(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(...)
    new_name: str = Field(...)

class RuntimeConfig(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    features: RuntimeConfigFeatures = Field(...)

class RuntimeConfigFeatures(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    ai_analysis: bool = Field(...)

class S3File(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['file'] | None = Field('file')
    name: str = Field(..., description='Имя узла (последний сегмент пути)')
    path: str = Field(..., description='Полный путь (prefix/key)')
    size: int = Field(..., description='Размер файла в байтах')
    last_modified: str | None = Field(None, description='Дата последнего изменения')
    etag: str | None = Field(None, description='ETag файла')
    storage_class: str | None = Field(None, description='Класс хранения (STANDARD, GLACIER и т.д.)')

class S3FileNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['s3'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: S3Properties = Field(...)
    secrets: S3Secrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class S3FileNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['s3'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: S3Properties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class S3FileNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: S3Properties | None = Field(None)
    secrets: S3Secrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class S3Folder(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['folder'] | None = Field('folder')
    name: str = Field(..., description='Имя узла (последний сегмент пути)')
    path: str = Field(..., description='Полный путь (prefix/key)')

class S3Properties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    bucket: str = Field(...)
    region_name: str | None = Field(None)
    endpoint_url: str | None = Field(None)
    use_ssl: bool | None = Field(True)
    path_style: bool | None = Field(False)
    signature_version: str | None = Field(None)
    prefix: str | None = Field(None)

class S3Secrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    access_token_id: str = Field(...)
    access_token_key: str = Field(...)
    session_token: str | None = Field(None)

class SFTPProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    host: str = Field(..., description='SFTP server hostname or IP address')
    port: int | None = Field(22, description='SFTP server port')
    username: str = Field(..., description='Username for authentication')
    private_key_path: str | None = Field(None, description='Path to private key file')
    initial_directory: str | None = Field(None, description='Initial directory after login')
    allow_agent: bool | None = Field(False, description='Allow SSH agent authentication')

class SFTPSecrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    password: str | None = Field(None)
    private_key_passphrase: str | None = Field(None)
    private_key_string: str | None = Field(None)

class SMBProtocolProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    host: str = Field(..., description='SMB server hostname or IP address')
    port: int = Field(..., description='SMB server port')
    share: str = Field(..., description='Shared folder name')
    username: str = Field(..., description='Username used to authenticate')

class SMBProtocolSecrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    password: str = Field(..., description='Password used to authenticate')

class SQLCodeMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    statements: list[SQLStatementMetadata] = Field(...)
    statement_count: int = Field(...)
    result_statement_count: int = Field(...)
    dialect_name: str | None = Field(None)
    dataframe_metadata: DataFrameMetadataOutput | None = Field(None)
    dataframe_metadata_statement_index: int | None = Field(None)

class SQLProperties(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    host: str = Field(...)
    port: int = Field(...)
    username: str = Field(...)
    database: str = Field(...)
    secure: bool | None = Field(False)
    connect_timeout: int | None = Field(30)
    send_receive_timeout: int | None = Field(60)
    sync_request_timeout: int | None = Field(60)
    ca_cert_string: str | None = Field(None)
    verify: bool | None = Field(False)

class SQLSecrets(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    password: str | None = Field(None)

class SQLStatementMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    statement_type: str = Field(...)
    category: Literal['read_only', 'data_mutating', 'ddl', 'execution', 'unknown'] = Field(...)
    returns_data: bool = Field(...)
    is_query_expression: bool = Field(...)

class ScheduleResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    project_id: str = Field(...)

class ServicesStatus(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    gateway: SystemInfo = Field(...)
    project_scheduler: SystemInfo | None = Field(...)
    task_workers: list[WorkerSystemInfo] | None = Field(...)

class SetupStatus(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    initialized: bool = Field(..., description='Is DVT fully initialized?')
    steps: list[SetupStep] | None = Field(None, description='Ordered statuses of all setup steps.')

class SetupStep(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    code: str = Field(..., description='Unique setup step code.')
    title: str = Field(..., description='Human-readable setup step title.')
    description: str | None = Field(None, description='Optional human-readable setup step description.')
    submit_label: str = Field(..., description='Label for the submit action.')
    completed: bool = Field(..., description='Whether the setup step is completed.')
    fields: list[SetupStepField] | None = Field(None, description='Fields required to submit the setup step.')

class SetupStepField(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    key: str = Field(..., description='Unique field key within the setup step.')
    label: str = Field(..., description='Human-readable field label.')
    type: Literal['text', 'password', 'email', 'number', 'boolean'] = Field(..., description='Frontend field type.')
    required: bool = Field(..., description='Whether the field must be submitted.')
    nullable: bool = Field(..., description='Whether null is allowed as a value.')
    value: str | int | float | bool | None = Field(None, description='Optional current value to prefill the setup form.')

class SetupStepSubmitRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    values: dict[str, Any] | None = Field(None, description='Setup step payload keyed by setup field key.')

class SftpFileNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['sftp'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SFTPProperties = Field(...)
    secrets: SFTPSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class SftpFileNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['sftp'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SFTPProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class SftpFileNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SFTPProperties | None = Field(None)
    secrets: SFTPSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class SmbprotocolFileNoDriverConnectionCreateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['smbprotocol'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SMBProtocolProperties = Field(...)
    secrets: SMBProtocolSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class SmbprotocolFileNoDriverConnectionReadResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    name: str = Field(...)
    kind: Literal['file'] = Field(...)
    type: Literal['smbprotocol'] = Field(...)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SMBProtocolProperties = Field(...)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    created_at: str = Field(...)
    updated_at: str = Field(...)
    deleted_at: str | None = Field(None)
    user_id: str | None = Field(..., description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(..., description='ID организации, которой принадлежит соединение')

class SmbprotocolFileNoDriverConnectionUpdateRequest(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    driver: None = Field(None)
    driver_options: None = Field(None)
    properties: SMBProtocolProperties | None = Field(None)
    secrets: SMBProtocolSecrets | None = Field(None)
    labels: dict[str, str] | None = Field(None)
    metadata: dict[str, Any] | None = Field(None)
    user_id: str | None = Field(None, description='ID пользователя, которому принадлежит соединение')
    organization_id: str | None = Field(None, description='ID организации, которой принадлежит соединение')

class SubgraphData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    displayname: str = Field(..., alias='displayName')
    color: str | None = Field(None)
    comment: str | None = Field(None)

class SubgraphDataUpdate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field(None)
    displayname: str | None = Field(None, alias='displayName')
    color: str | None = Field(None)
    comment: str | None = Field(None)

class SubgraphUISchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    type: str = Field(...)
    position: Position = Field(...)
    selected: bool | None = Field(False)
    expanded: bool | None = Field(True)
    data: SubgraphData = Field(...)

class SubgraphUIUpdateSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    data: SubgraphDataUpdate | None = Field(None)
    type: str | None = Field(None)
    position: Position | None = Field(None)
    selected: bool | None = Field(None)
    expanded: bool | None = Field(None)

class SystemInfo(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    hostname: str = Field(...)
    os_type: str = Field(...)
    os_release: str = Field(...)
    os_version: str = Field(...)
    system_uptime_seconds: float = Field(...)
    app_uptime_seconds: float = Field(...)
    cpu_percent: float = Field(...)
    cpu_cores_physical: int = Field(...)
    cpu_cores_logical: int = Field(...)
    ram_total: float = Field(...)
    ram_available: float = Field(...)
    ram_used: float = Field(...)
    ram_used_percent: float = Field(...)
    disk_total: float = Field(...)
    disk_used: float = Field(...)
    disk_free: float = Field(...)
    disk_used_percent: float = Field(...)
    network_bytes_sent: int = Field(...)
    network_bytes_recv: int = Field(...)
    process_count: int = Field(...)

class SystemVariableDefinitionModel(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: IO = Field(..., description='Тип системной переменной')
    required: bool = Field(..., description='Обязательна ли системная переменная в runtime')
    display_name: str | None = Field(None, description='Отображаемое имя системной переменной')
    description: str | None = Field(None, description='Описание системной переменной')

class TableCreateSpec(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    primary_key_cols: str | list[str] | None = Field(None)
    indexes: list[IndexSpec] | None = Field(None)
    foreign_keys: list[ForeignKeySpec] | None = Field(None)
    clickhouse: ClickHouseEngineSpec | None = Field(None)

class TaskInfo(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    task_id: str = Field(..., description="Task's ID")
    status: TaskStatus = Field(..., description="Task's status")
    started_at: str | None = Field(None, description='Task processing started time (if started)')
    message: str | None = Field(None, description="Optional task's message")
    source: TaskSource = Field(..., description='Task source')

class TaskResponse(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool = Field(..., description='Успешно ли выполнено')
    message: str = Field(..., description='Сообщение')
    task_id: str = Field(...)

class UserFileTreeSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(...)
    nodes: list[S3File | S3Folder | FTPFile | FTPFolder] = Field(...)
    is_truncated: bool = Field(...)
    next_token: str | None = Field(None)

class UserReadSchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    external_id: str | None = Field(None)
    email: str = Field(...)
    user_name: str | None = Field(None)
    role: DVTDefaultRoles | str | None = Field('user')
    organization_id: str = Field(..., description='ID организации пользователя')

class ValidationError(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    loc: list[str | int] = Field(...)
    msg: str = Field(...)
    type: str = Field(...)

class VersionInfo(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    version: str = Field(...)

class WorkerSystemInfo(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    hostname: str = Field(...)
    os_type: str = Field(...)
    os_release: str = Field(...)
    os_version: str = Field(...)
    system_uptime_seconds: float = Field(...)
    app_uptime_seconds: float = Field(...)
    cpu_percent: float = Field(...)
    cpu_cores_physical: int = Field(...)
    cpu_cores_logical: int = Field(...)
    ram_total: float = Field(...)
    ram_available: float = Field(...)
    ram_used: float = Field(...)
    ram_used_percent: float = Field(...)
    disk_total: float = Field(...)
    disk_used: float = Field(...)
    disk_free: float = Field(...)
    disk_used_percent: float = Field(...)
    network_bytes_sent: int = Field(...)
    network_bytes_recv: int = Field(...)
    process_count: int = Field(...)
    worker_id: str = Field(...)
    status: WorkerStatus | None = Field('online')
    first_seen_at: float | None = Field(None)
    last_heartbeat_at: float | None = Field(None)
    last_heartbeat_received_at: float | None = Field(None)
    last_status_change_at: float | None = Field(None)
    offline_since: float | None = Field(None)
    heartbeat_age_sec: float | None = Field(None)
    has_running_task: bool | None = Field(False)
    running_task_ram_used: float | None = Field(None)
    running_task_ram_used_percent: float | None = Field(None)

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel1(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('REGISTRY_NOT_FOUND')
    code: str | None = Field('EXCEPTION_404')
    description: str | None = Field('Exception не найден')
    category: str | None = Field('GATEWAY_EXCEPTION_REGISTRY')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel2(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('REGISTRY_VALIDATION_ERROR')
    code: str | None = Field('EXCEPTION_400')
    description: str | None = Field('Ошибка при создании и регистрации Exception')
    category: str | None = Field('GATEWAY_EXCEPTION_REGISTRY')
    type: str | None = Field('HTTP_GENERATED')

class AdminUserCreate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    auth_provider: Literal['email'] | None = Field('email')
    email: str = Field(...)
    password: str = Field(...)
    external_id: str | None = Field(None)
    user_name: str | None = Field(None)
    role: str | None = Field(None)

class AdminUserUpdate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    email: str | None = Field(None)
    password: str | None = Field(None)
    external_id: str | None = Field(None)
    user_name: str | None = Field(None)
    role: str | None = Field(None)
    is_active: bool | None = Field(None)
    is_verified: bool | None = Field(None)

class ApiTokenCreate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    description: str | None = Field(None)
    expires_at: int | None = Field(None, description='Expiration timestamp datetime in seconds')
    whitelisted_ip_addresses: list[str] | None = Field(None, description='List of whitelisted IP addresses. If set, the token will be valid only for requests from these IP addresses.')

class ApiTokenCreatedData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    token: str = Field(...)

class ApiTokensListData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    tokens: list[UserTokenRead] = Field(...)

class AuthenticatedData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    is_authenticated: bool | None = Field(True)

class CommonDataNextStepResponseManagedUserData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: ManagedUserData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseApiTokenCreatedData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: ApiTokenCreatedData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseApiTokenEmptyData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: ApiTokenEmptyData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseApiTokensListData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: ApiTokensListData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseAuthenticatedData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: AuthenticatedData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseManagedUserData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: ManagedUserData | None = Field(None, description='Structured payload returned by the endpoint.')

class CommonDataResponseUserProfileData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    success: bool | None = Field(True, description='Success status')
    message: str | None = Field(None, description='Message')
    next_step: str | None = Field(None, description='Next step for the user. Used in async operations.')
    data: UserProfileData | None = Field(None, description='Structured payload returned by the endpoint.')

class ManagedUserData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    user_identifier: str | int | None = Field(None)
    email: str = Field(...)
    auth_provider: str = Field(...)
    is_verified: bool = Field(...)
    is_active: bool = Field(...)
    user_name: str | None = Field(None)
    external_id: str | None = Field(None)
    role: str | None = Field(None)

class UserLogin(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    auth_provider: Literal['email'] = Field(...)
    email: str = Field(...)
    password: str = Field(...)

class UserProfileData(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    mail: str = Field(...)
    user_name: str | None = Field(None)
    user_id: str | None = Field(None)

class UserTokenRead(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    token_type: str = Field(...)
    name: str | None = Field(...)
    created_at: str = Field(...)
    expires_at: int | None = Field(...)

class DataFrameMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['DATAFRAME'] | None = Field('DATAFRAME')
    columns: list[Column] = Field(...)
    rows_num: int | None = Field(None)
    size: int | None = Field(None, description='Размер DataFrame в байтах')

class FTPDirectoryMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    host: str = Field(..., description='Адрес хоста')
    current_path: str | None = Field('/', description='Текущий путь просмотра')
    nodes: list[FTPFile | FTPFolder] | None = Field(None, description='Список файлов и папок в директории')
    total_size: int | None = Field(0, description='Общий размер файлов в текущей выборке')
    files_count: int | None = Field(0, description='Количество файлов')
    folders_count: int | None = Field(0, description='Количество папок')

class FTPMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['FTP'] | None = Field('FTP')
    connection_id: str = Field(..., description='Connection ID')
    connection_string: str | None = Field(None, description='Безопасная строка подключения')
    connection_prefix: str | None = Field(None, description='Connection prefix')
    host: str = Field(..., description='Хост FTP сервера')
    port: int | None = Field(21, description='Порт')
    mode: str | None = Field('ftp', description='Режим (ftp/ftps)')
    username: str | None = Field(None, description='Имя пользователя')
    anonymous: bool | None = Field(False, description='Анонимный вход')
    initial_directory: str | None = Field(None, description='Стартовый каталог')
    encoding: str | None = Field('utf-8', description='Кодировка')
    directory: FTPDirectoryMetadata | None = Field(None, description='Метаданные начальной директории')

class JSONFlattenCandidate(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    path: str = Field(..., description='Machine-readable JSON path.')
    display_path: str = Field(..., description='Human-readable JSON path.')
    kind: JSONFlattenCandidateKind = Field(..., description='Flatten candidate kind.')
    node_kind: JSONNodeKind = Field(..., description='Observed node kind for the candidate path.')
    confidence: float | None = Field(0.0, description='Heuristic confidence score.')
    reason: str | None = Field('', description='Explanation of why the candidate was inferred.')

class JSONMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['JSON'] | None = Field('JSON')
    response: Any | None = Field(None)
    root: JSONStructureNode | None = Field(None, description='Inferred JSON structure root.')
    flatten_candidates: list[JSONFlattenCandidate] | None = Field(None, description='Suggested paths for JSON normalization.')
    stats: JSONStructureStats | None = Field(None, description='Aggregated JSON structure statistics.')
    inferred_schema: dict[str, Any] | None = Field(None, description='Schema-like serialized representation of the inferred JSON structure.')
    structure_truncated: bool | None = Field(False, description='Whether inference was truncated because of configured limits.')

class JSONStructureNode(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description="Node name. For array items uses '[]', root uses '$'.")
    path: str = Field(..., description='Machine-readable JSON path.')
    display_path: str = Field(..., description='Human-readable JSON path.')
    kind: JSONNodeKind = Field(..., description='Effective JSON node kind.')
    required: bool | None = Field(True, description='Whether the node is present in every sampled parent.')
    nullable: bool | None = Field(False, description='Whether null was observed for this path.')
    occurrences: int | None = Field(0, description='How many sampled observations reached this node.')
    kinds: list[JSONNodeKind] | None = Field(None, description='Observed non-null kinds when the node is a UNION.')
    object_keys: list[str] | None = Field(None, description='Observed object keys for OBJECT nodes.')
    children: list[JSONStructureNode] | None = Field(None, description='Child nodes for OBJECT and ARRAY nodes.')
    item_kind: JSONNodeKind | None = Field(None, description='Observed item kind for ARRAY nodes.')
    array_min_items: int | None = Field(None, description='Minimum observed array size.')
    array_max_items: int | None = Field(None, description='Maximum observed array size.')
    sampled_items: int | None = Field(None, description='How many array items were sampled for structure inference.')
    examples: list[Any] | None = Field(None, description='Sample values for scalar nodes.')

class JSONStructureStats(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    total_nodes: int | None = Field(0)
    object_nodes: int | None = Field(0)
    array_nodes: int | None = Field(0)
    scalar_nodes: int | None = Field(0)
    union_nodes: int | None = Field(0)
    max_depth: int | None = Field(0)

class KafkaBroker(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    node_id: int = Field(...)
    host: str = Field(...)
    port: int = Field(...)
    rack: str | None = Field(None)

class KafkaCluster(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    controller_id: int | None = Field(None)
    brokers: list[KafkaBroker] | None = Field([])

class KafkaMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['KAFKA'] | None = Field('KAFKA')
    cluster: KafkaCluster = Field(...)
    topics: list[KafkaTopic] = Field(...)
    bootstrap_servers: list[str] = Field(...)
    connection_string: str = Field(...)

class KafkaTopic(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(...)
    partitions_count: int = Field(...)
    replication_factor: int = Field(...)
    is_internal: bool | None = Field(False)

class LogEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['LOG_EVENT'] | None = Field('LOG_EVENT')
    timestamp: int | None = Field(None)
    entry: LogEntrySchema = Field(..., description='Запись лога')

class NodeExecutionStatusEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['NODE_EXECUTION_STATUS'] | None = Field('NODE_EXECUTION_STATUS')
    timestamp: int | None = Field(None)
    task_id: str = Field(..., description='ID текущей задачи')
    node_id: str = Field(..., description='ID выполняемого узла (для отображения)')
    status: ExecutionStatus = Field(..., description='Текущий статус выполнения узла')
    execution_mode: PipelineExecutionMode = Field(..., description='Режим выполнения задачи')
    message: str | None = Field(None, description='Сообщение об ошибке узла')

class NodeMetadataEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['NODE_METADATA'] | None = Field('NODE_METADATA')
    timestamp: int | None = Field(None)
    project_id: str = Field(..., description='ID проекта')
    task_id: str = Field(..., description='ID задачи')
    node_id: str = Field(..., description='ID узла')
    metadata: dict[str, DataFrameMetadata | DBMetadata | KafkaMetadata | SeriesMetadata | S3Metadata | JSONMetadata | FTPMetadata | SMBMetadata | VariableMapMetadata | None] = Field(..., description='Метаданные узла ({output_name: MetaData})')

class PingEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['PING'] | None = Field('PING')
    timestamp: int | None = Field(None)

class ProgressEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['PROGRESS'] | None = Field('PROGRESS')
    timestamp: int | None = Field(None)
    value: int = Field(..., description='Текущее значение прогресса')
    max: int = Field(..., description='Максимальное значение прогресса')
    task_id: str = Field(..., description='ID текущей задачи')
    node_id: str | None = Field(None, description='ID узла, для которого отображается прогресс')

class S3Bucket(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя бакета')
    creation_date: str | None = Field(None, description='Дата создания бакета')
    nodes: list[S3File | S3Folder] | None = Field(None, description='Список узлов (папок и файлов) в бакете')
    total_size: int | None = Field(0, description='Общий размер всех файлов в байтах')
    files_count: int | None = Field(0, description='Количество файлов')
    folders_count: int | None = Field(0, description='Количество папок')

class S3Metadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['S3'] | None = Field('S3')
    connection_id: str = Field(..., description='Connection ID')
    connection_prefix: str | None = Field(None, description='Connection prefix')
    bucket: S3Bucket | None = Field(None, description='Метаданные бакета в S3.')
    endpoint_url: str | None = Field(None, description='URL эндпоинта S3 (для совместимых S3 хранилищ).')
    region: str | None = Field(None, description='Регион S3.')
    connection_string: str | None = Field(None, description='Строка подключения к S3 (без учетных данных).')

class SMBDirectoryMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    host: str = Field(..., description='Адрес хоста')
    share: str = Field(..., description='Имя SMB share')
    current_path: str | None = Field('/', description='Текущий путь просмотра')
    nodes: list[SMBFile | SMBFolder] | None = Field(None, description='Список файлов и папок в директории')
    total_size: int | None = Field(0, description='Общий размер файлов в текущей выборке')
    files_count: int | None = Field(0, description='Количество файлов')
    folders_count: int | None = Field(0, description='Количество папок')

class SMBFile(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['file'] | None = Field('file')
    name: str = Field(..., description='Имя узла (название файла или папки)')
    path: str = Field(..., description='Полный путь к узлу внутри SMB share')
    size: int = Field(..., description='Размер файла в байтах')
    last_modified: str | None = Field(None, description='Дата последнего изменения')
    permissions: str | None = Field(None, description='Права доступа')

class SMBFolder(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['folder'] | None = Field('folder')
    name: str = Field(..., description='Имя узла (название файла или папки)')
    path: str = Field(..., description='Полный путь к узлу внутри SMB share')
    permissions: str | None = Field(None, description='Права доступа')

class SMBMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['SMB'] | None = Field('SMB')
    connection_id: str = Field(..., description='Connection ID')
    connection_string: str | None = Field(None, description='Безопасная строка подключения')
    connection_prefix: str | None = Field(None, description='Connection prefix')
    host: str = Field(..., description='Хост SMB сервера')
    port: int | None = Field(445, description='Порт')
    share: str = Field(..., description='Имя SMB share')
    username: str | None = Field(None, description='Имя пользователя')
    initial_directory: str | None = Field('/', description='Стартовый каталог внутри share')
    directory: SMBDirectoryMetadata | None = Field(None, description='Метаданные текущей директории SMB')

class SeriesMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['SERIES'] | None = Field('SERIES')
    name: str = Field(..., description='Имя колонки')
    column_data: Column = Field(...)

class StatusUpdateEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['STATUS'] | None = Field('STATUS')
    timestamp: int | None = Field(None)

class TaskError(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    message: str = Field(..., description='Сообщение об ошибке')

class TaskExecutionStatusEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['TASK_EXECUTION_STATUS'] | None = Field('TASK_EXECUTION_STATUS')
    timestamp: int | None = Field(None)
    task_id: str = Field(..., description='ID текущей задачи')
    mode: PipelineExecutionMode = Field(..., description='Режим выполнения задачи')
    status: TaskStatus = Field(..., description='Текущий статус выполнения задачи')
    error: TaskError | None = Field(None)

class TaskExecutionTelemetryEvent(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['TASK_EXECUTION_TELEMETRY'] | None = Field('TASK_EXECUTION_TELEMETRY')
    timestamp: int | None = Field(None)
    task_id: str = Field(..., description='ID of the task, for which the telemetry is reported')
    hostname: str = Field(..., description='Hostname, on which the task process is running')
    pid: int = Field(..., description='PID of the process that is executing the task')
    rss_bytes: int = Field(..., description='Resident set size of the executing task process')
    memory_limit_bytes: int | None = Field(None, description='Effective memory limit of the worker execution environment')
    system_ram_used_percent: float = Field(..., description='Current RAM pressure on the host/container')

class VariableDescriptorMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str = Field(..., description='Имя переменной')
    type: Literal['STRING', 'BOOLEAN', 'INT', 'FLOAT', 'DATETIME', 'TIMEDELTA', 'JSON'] = Field(..., description='Тип переменной')
    var_type: Literal['user', 'system'] | None = Field('user', description='Область переменной')
    is_list_type: bool | None = Field(False, description='Признак переменной-списка')
    value_state: Literal['resolved', 'unresolved'] | None = Field('resolved', description='Состояние значения переменной')

class VariableMapMetadata(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    type: Literal['VARIABLE_MAP'] | None = Field('VARIABLE_MAP')
    variables: list[VariableDescriptorMetadata] | None = Field(None, description='Метаданные переменных выходного порта')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel10(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('NODE_ERROR')
    code: str | None = Field('INPUT_ERROR')
    description: str | None = Field('Проблема с входом узла')
    category: str | None = Field('UNKNOWN')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel11(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('NODE_ERROR')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Узел с указанным ID не найден')
    category: str | None = Field('UNKNOWN')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel12(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('USER_AUTH')
    code: str | None = Field('INVALID_CREDENTIALS')
    description: str | None = Field('Некорректные данные для входа')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel13(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('BAD_PIPELINE')
    code: str | None = Field('PIPELINE_400')
    description: str | None = Field('Ошибка при валидации пайплайна')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel14(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DUPLICATE_PIPELINE')
    code: str | None = Field('PIPELINE_400')
    description: str | None = Field('Дублированный пайплайн')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel15(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_NOT_FOUND')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Проект не найден')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel16(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECTS_NOT_FOUND')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Проект не найден')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel17(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('MAX_PROJECTS_REACHED')
    code: str | None = Field('MAX_PROJECT')
    description: str | None = Field('Достигнуто максимальное количество проектов')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel18(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATABASE')
    code: str | None = Field('VIOLATION_ERROR')
    description: str | None = Field('При запросе нарушена ссылочная целостность')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel19(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATABASE')
    code: str | None = Field('TABLE_ALREADY_EXISTS')
    description: str | None = Field('Таблица уже создана')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel20(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATABASE')
    code: str | None = Field('VIOLATION_ERROR')
    description: str | None = Field('При запросе нарушена уникальность данных по ключам')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel21(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('GRAPH_NODE_NOT_FOUND')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Некоторые ноды не были найдены, или доступ ограничен')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel22(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('S3_CONFIGURATION')
    code: str | None = Field('S3_ERROR')
    description: str | None = Field('Ошибка в конфигурации S3')
    category: str | None = Field('S3')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel23(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_AND_WORKER_NOT_FOUND')
    code: str | None = Field('PROJECT_404')
    description: str | None = Field('Проект и ссылка на worker не найдены в БД')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel24(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('STORAGE_CLIENT_ERROR')
    code: str | None = Field('CLIENT_ERROR')
    description: str | None = Field('Клиентская ошибка')
    category: str | None = Field('GATEWAY_STORAGE')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel25(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('STORAGE_CONFIGURATION_ERROR')
    code: str | None = Field('CONFIGURATION_ERROR')
    description: str | None = Field('Ошибка в конфигурации для S3')
    category: str | None = Field('GATEWAY_STORAGE')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel26(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_SERVICE')
    code: str | None = Field('FAILED_ACTION')
    description: str | None = Field('Ошибка при выполнении действия')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel27(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_SERVICE')
    code: str | None = Field('UNSUPPORTED_ACTION_400')
    description: str | None = Field('Ошибка при выполнении запроса, невалидное действие')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel28(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CACHE_ENTRY_BY_INDEX')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Cache entry not found')
    category: str | None = Field('TASK_WORKER_CACHE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel29(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CACHE_ENTRY_BY_KEY')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Cache entry not found')
    category: str | None = Field('TASK_WORKER_CACHE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel3(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_NOT_FOUND')
    code: str | None = Field('PROJECT_404')
    description: str | None = Field('Проект не найден')
    category: str | None = Field('PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel30(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_NOT_FOUND')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Задача не найдена')
    category: str | None = Field('TASK_WORKER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel31(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('WORKER_CLIENT')
    code: str | None = Field('CONNECTION_ERROR')
    description: str | None = Field('Ошибка при соединении Worker Client')
    category: str | None = Field('WORKER_CLIENT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel32(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('WORKER_CLIENT')
    code: str | None = Field('CLIENT_ERROR')
    description: str | None = Field('Клиентская ошибка Worker Client')
    category: str | None = Field('WORKER_CLIENT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel33(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('HTTP_REQUEST_TIMEOUT')
    code: str | None = Field('TIMEOUT')
    description: str | None = Field('Истекло время подключения')
    category: str | None = Field('TASK_WORKER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel34(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('HTTP_REQUEST_SERVICE_UNAVAILABLE')
    code: str | None = Field('SERVICE_UNAVAILABLE')
    description: str | None = Field('Сервис недоступен')
    category: str | None = Field('TASK_WORKER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel35(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('HTTP_REQUEST_BAD_REQUEST')
    code: str | None = Field('BAD_REQUEST')
    description: str | None = Field('Ошибка запроса')
    category: str | None = Field('TASK_WORKER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel36(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_NOT_FOUND')
    code: str | None = Field('NOT_FOUND')
    description: str | None = Field('Задача не найдена')
    category: str | None = Field('PROJECT_SCHEDULER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel37(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_ALREADY_SCHEDULED')
    code: str | None = Field('ALREADY_SCHEDULED')
    description: str | None = Field('Задача уже запланирована')
    category: str | None = Field('PROJECT_SCHEDULER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel38(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('TASK_ALREADY_RUNNING')
    code: str | None = Field('ALREADY_RUNNING')
    description: str | None = Field('Задача уже запущена')
    category: str | None = Field('PROJECT_SCHEDULER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel39(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('MAX_PENDING_TASKS_REACHED')
    code: str | None = Field('MAX_PENDING_TASKS')
    description: str | None = Field('Достигнуто максимальное количество ожидающих задач')
    category: str | None = Field('PROJECT_SCHEDULER_TASKS')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel4(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('ORCHESTRATOR_RPC_ERROR')
    code: str | None = Field('ORCHESTRATOR_503')
    description: str | None = Field('Orchestrator RPC error')
    category: str | None = Field('ORCHESTRATOR_CLIENT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel40(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('SQL_QUERY_METADATA_EXTRACTION_ERROR')
    code: str | None = Field('METADATA_EXTRACTION_ERROR')
    description: str | None = Field('Ошибка при извлечении метаданных из SQL запроса')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel41(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CREATE_TABLE_ERROR')
    code: str | None = Field('CREATE_TABLE_ERROR')
    description: str | None = Field('Ошибка при создании таблицы')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel42(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DDL_ERROR')
    code: str | None = Field('DDL_ERROR')
    description: str | None = Field('Ошибка при выполнении DDL')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel43(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('STORAGE_FTP')
    code: str | None = Field('STORAGE_FTP')
    description: str | None = Field('Ошибка в конфигурации для FTP')
    category: str | None = Field('FTP')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel44(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_NOT_FOUND')
    code: str | None = Field('CRUD_PROJECT_404')
    description: str | None = Field('Проект не найден')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel45(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_ACCESS_FORBIDDEN')
    code: str | None = Field('CRUD_PROJECT_403')
    description: str | None = Field('Доступ к проекту запрещен')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel46(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_VARIABLE_NOT_FOUND')
    code: str | None = Field('CRUD_PROJECT_VARIABLE_404')
    description: str | None = Field('Переменная проекта не найдена')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel47(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_VARIABLE_ALREADY_EXISTS')
    code: str | None = Field('CRUD_PROJECT_VARIABLE_409')
    description: str | None = Field('Переменная проекта уже существует')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel48(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_VARIABLE_ALREADY_EXISTS')
    code: str | None = Field('PROJECT_VARIABLE_409')
    description: str | None = Field('Project variable already exists')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel49(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_VARIABLE_OT_FOUND')
    code: str | None = Field('PROJECT_VARIABLE_404')
    description: str | None = Field('Project variable not found')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel5(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('ORCHESTRATOR_TASK_REJECTED')
    code: str | None = Field('ORCHESTRATOR_500')
    description: str | None = Field('Orchestrator rejected task')
    category: str | None = Field('ORCHESTRATOR_CLIENT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel50(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_ACCESS_FORBIDDEN')
    code: str | None = Field('PROJECT_ACCESS_403')
    description: str | None = Field('Project access forbidden')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel51(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('PROJECT_NOT_FOUND')
    code: str | None = Field('PROJECT_400')
    description: str | None = Field('Project not found')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel52(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATA_FRAME_META_NOT_FOUND')
    code: str | None = Field('DATA_FRAME_404')
    description: str | None = Field('DDFMeta not found')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel53(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATA_FRAME_NOT_FOUND')
    code: str | None = Field('DATA_FRAME_404')
    description: str | None = Field('DataFrame not found')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel54(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('JSON_NOT_FOUND')
    code: str | None = Field('JSON_404')
    description: str | None = Field('JSON not found')
    category: str | None = Field('GATEWAY_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel55(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_NOT_FOUND')
    code: str | None = Field('CRUD_PROJECT_404')
    description: str | None = Field('Проект не найден')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel56(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_ACCESS_FORBIDDEN')
    code: str | None = Field('CRUD_PROJECT_403')
    description: str | None = Field('Доступ к проекту запрещен')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel57(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_VARIABLE_NOT_FOUND')
    code: str | None = Field('CRUD_PROJECT_VARIABLE_404')
    description: str | None = Field('Переменная проекта не найдена')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel58(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_PROJECT_VARIABLE_ALREADY_EXISTS')
    code: str | None = Field('CRUD_PROJECT_VARIABLE_409')
    description: str | None = Field('Переменная проекта уже существует')
    category: str | None = Field('CRUD_PROJECT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel59(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_GRAPH_NODE_NOT_FOUND')
    code: str | None = Field('CRUD_GRAPH_NODE_404')
    description: str | None = Field('Узел графа не найден')
    category: str | None = Field('CRUD_GRAPH_NODE')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel6(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('ORCHESTRATOR_INVALID_STATS')
    code: str | None = Field('ORCHESTRATOR_500')
    description: str | None = Field('Orchestrator invalid stats')
    category: str | None = Field('ORCHESTRATOR_CLIENT')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel60(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_GRAPH_EDGE_NOT_FOUND')
    code: str | None = Field('CRUD_GRAPH_EDGE_404')
    description: str | None = Field('Ребро графа не найдено')
    category: str | None = Field('CRUD_GRAPH_EDGE')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel61(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_SUBGRAPH_NOT_FOUND')
    code: str | None = Field('CRUD_SUBGRAPH_404')
    description: str | None = Field('Подграф не найден')
    category: str | None = Field('CRUD_SUBGRAPH')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel62(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_GRAPH_NOT_FOUND')
    code: str | None = Field('CRUD_GRAPH_404')
    description: str | None = Field('Граф не найден')
    category: str | None = Field('CRUD_GRAPH')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel63(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_TASK_NOT_FOUND')
    code: str | None = Field('CRUD_TASK_404')
    description: str | None = Field('Задача не найдена')
    category: str | None = Field('CRUD_TASK')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel64(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_INVALID_TASK_STATUS_TRANSITION')
    code: str | None = Field('CRUD_TASK_STATUS_409')
    description: str | None = Field('Недопустимый переход статуса задачи')
    category: str | None = Field('CRUD_TASK')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel65(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_NOT_FOUND')
    code: str | None = Field('CRUD_USER_404')
    description: str | None = Field('Пользователь не найден')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel66(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_ALREADY_EXISTS')
    code: str | None = Field('CRUD_USER_409')
    description: str | None = Field('Пользователь уже существует')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel67(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_FORBIDDEN')
    code: str | None = Field('CRUD_USER_403')
    description: str | None = Field('Действие над пользователем запрещено')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel68(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_ALREADY_EXISTS')
    code: str | None = Field('CRUD_USER_409')
    description: str | None = Field('Пользователь уже существует')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel69(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_NOT_FOUND')
    code: str | None = Field('CRUD_USER_404')
    description: str | None = Field('Пользователь не найден')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel7(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATAFRAME')
    code: str | None = Field('DATAFRAME_404')
    description: str | None = Field('DataFrame не найден')
    category: str | None = Field('DATAFRAME')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel70(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_USER_FORBIDDEN')
    code: str | None = Field('CRUD_USER_403')
    description: str | None = Field('Действие над пользователем запрещено')
    category: str | None = Field('CRUD_USER')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel71(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_NOT_FOUND')
    code: str | None = Field('CRUD_ORGANIZATION_404')
    description: str | None = Field('Организация не найдена')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel72(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_INN_CONFLICT')
    code: str | None = Field('CRUD_ORGANIZATION_409')
    description: str | None = Field('Организация с таким ИНН уже существует')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel73(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_NOT_FOUND')
    code: str | None = Field('CRUD_ORGANIZATION_404')
    description: str | None = Field('Организация не найдена')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel74(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_INN_CONFLICT')
    code: str | None = Field('CRUD_ORGANIZATION_409')
    description: str | None = Field('Организация с таким ИНН уже существует')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel75(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_FORBIDDEN')
    code: str | None = Field('CRUD_ORGANIZATION_403')
    description: str | None = Field('Действие над организацией запрещено')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel76(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_ORGANIZATION_INN_INVALID')
    code: str | None = Field('CRUD_ORGANIZATION_400')
    description: str | None = Field('Некорректный ИНН организации')
    category: str | None = Field('CRUD_ORGANIZATION')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel77(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('REGISTRY_NOT_FOUND')
    code: str | None = Field('EXCEPTION_404')
    description: str | None = Field('Exception не найден')
    category: str | None = Field('GATEWAY_EXCEPTION_REGISTRY')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel78(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('REGISTRY_VALIDATION_ERROR')
    code: str | None = Field('EXCEPTION_400')
    description: str | None = Field('Ошибка при создании и регистрации Exception')
    category: str | None = Field('GATEWAY_EXCEPTION_REGISTRY')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel79(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_QUEUE_TOPIC_NOT_FOUND')
    code: str | None = Field('CRUD_QUEUE_TOPIC_404')
    description: str | None = Field('Топик очереди не найден')
    category: str | None = Field('CRUD_QUEUE_TOPIC')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel8(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('DATABASE')
    code: str | None = Field('DATABASE_CONNECTION_404')
    description: str | None = Field('DB подключение не найдено')
    category: str | None = Field('DATABASE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel80(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CRUD_QUEUE_TOPIC_ALREADY_EXISTS')
    code: str | None = Field('CRUD_QUEUE_TOPIC_409')
    description: str | None = Field('Топик очереди уже существует')
    category: str | None = Field('CRUD_QUEUE_TOPIC')
    type: str | None = Field('CUSTOM')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel81(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('CONNECTION_NOT_FOUND')
    code: str | None = Field('CONNECTION_404')
    description: str | None = Field('Connection not found')
    category: str | None = Field('GATEWAY_STORAGE')
    type: str | None = Field('HTTP_GENERATED')

class SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel9(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    name: str | None = Field('GRAPH')
    code: str | None = Field('CYCLE_ERROR')
    description: str | None = Field('Обнаружен цикл зависимостей в графе.')
    category: str | None = Field('UNKNOWN')
    type: str | None = Field('CUSTOM')

class GraphNodeUISchema(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='allow')
    id: str = Field(...)
    type: str = Field(...)
    subgraphid: str | None = Field(None, alias='subgraphId')
    position: Position = Field(...)
    selected: bool | None = Field(False)
    data: GraphNodeData = Field(...)

class ODBCDriverOptions(SDKBaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    driver_name: str = Field(...)

Event: TypeAlias = LogEvent | NodeExecutionStatusEvent | TaskExecutionStatusEvent | TaskExecutionTelemetryEvent | NodeMetadataEvent | PingEvent | ProgressEvent | StatusUpdateEvent

Metadata: TypeAlias = DataFrameMetadata | DBMetadata | KafkaMetadata | SeriesMetadata | S3Metadata | JSONMetadata | FTPMetadata | SMBMetadata

NodeOutputMetadata: TypeAlias = DataFrameMetadata | DBMetadata | KafkaMetadata | SeriesMetadata | S3Metadata | JSONMetadata | FTPMetadata | SMBMetadata | VariableMapMetadata

NodeMetadata: TypeAlias = dict[str, DataFrameMetadata | DBMetadata | KafkaMetadata | SeriesMetadata | S3Metadata | JSONMetadata | FTPMetadata | SMBMetadata | VariableMapMetadata | None]

PipelineMetadata: TypeAlias = dict[str, dict[str, DataFrameMetadata | DBMetadata | KafkaMetadata | SeriesMetadata | S3Metadata | JSONMetadata | FTPMetadata | SMBMetadata | VariableMapMetadata | None]]

RegisteredException: TypeAlias = SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel1 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel2 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel3 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel4 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel5 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel6 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel7 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel8 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel9 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel10 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel11 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel12 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel13 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel14 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel15 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel16 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel17 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel18 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel19 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel20 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel21 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel22 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel23 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel24 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel25 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel26 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel27 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel28 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel29 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel30 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel31 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel32 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel33 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel34 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel35 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel36 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel37 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel38 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel39 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel40 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel41 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel42 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel43 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel44 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel45 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel46 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel47 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel48 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel49 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel50 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel51 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel52 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel53 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel54 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel55 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel56 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel57 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel58 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel59 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel60 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel61 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel62 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel63 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel64 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel65 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel66 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel67 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel68 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel69 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel70 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel71 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel72 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel73 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel74 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel75 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel76 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel77 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel78 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel79 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel80 | SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel81

NodeInputValue: TypeAlias = NodeInputExpressionValue | NodeInputConstantValue | NodeInputLinkValue

NodeInputValues: TypeAlias = dict[str, NodeInputExpressionValue | NodeInputConstantValue | NodeInputLinkValue]

DBConnectionCreateV1: TypeAlias = ClickhouseSqlNativeDefaultDriverConnectionCreateRequest | ClickhouseSqlHttpConnectionCreateRequest | FtpFileNoDriverConnectionCreateRequest | KafkaQueueNoDriverConnectionCreateRequest | MongodbSqlNoDriverConnectionCreateRequest | MssqlSqlPyodbcDefaultDriverConnectionCreateRequest | MssqlSqlAioodbcConnectionCreateRequest | MysqlSqlPymysqlDefaultDriverConnectionCreateRequest | MysqlSqlAiomysqlConnectionCreateRequest | OracleSqlOracledbDefaultDriverConnectionCreateRequest | PostgresSqlPsycopgDefaultDriverConnectionCreateRequest | PostgresSqlPsycopg2ConnectionCreateRequest | PostgresSqlAsyncpgConnectionCreateRequest | S3FileNoDriverConnectionCreateRequest | SftpFileNoDriverConnectionCreateRequest | SmbprotocolFileNoDriverConnectionCreateRequest

DBConnectionReadV1: TypeAlias = ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse

DBConnectionUpdateV1: TypeAlias = ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest | ClickhouseSqlHttpConnectionUpdateRequest | FtpFileNoDriverConnectionUpdateRequest | KafkaQueueNoDriverConnectionUpdateRequest | MongodbSqlNoDriverConnectionUpdateRequest | MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest | MssqlSqlAioodbcConnectionUpdateRequest | MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest | MysqlSqlAiomysqlConnectionUpdateRequest | OracleSqlOracledbDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopg2ConnectionUpdateRequest | PostgresSqlAsyncpgConnectionUpdateRequest | S3FileNoDriverConnectionUpdateRequest | SftpFileNoDriverConnectionUpdateRequest | SmbprotocolFileNoDriverConnectionUpdateRequest

AIAnalysisCreateResponseSchema.model_rebuild()
AIAnalysisCreateSchema.model_rebuild()
AIAnalysisHistoryItemSchema.model_rebuild()
AIAnalysisHistoryResponseSchema.model_rebuild()
AIAnalysisReadSchema.model_rebuild()
AIServiceAnalysisResultSchema.model_rebuild()
AIServiceRecommendedActionSchema.model_rebuild()
AIServiceSourceContextItemSchema.model_rebuild()
AdminUserCreateSchema.model_rebuild()
AdminUserReadSchema.model_rebuild()
AdminUserUpdateSchema.model_rebuild()
AppSettingsDccReadSchema.model_rebuild()
AppSettingsDccUpdateSchema.model_rebuild()
AppSettingsLicenseReadSchema.model_rebuild()
AppSettingsLicenseUpdateSchema.model_rebuild()
AppSettingsRuntimeReadSchema.model_rebuild()
AppSettingsRuntimeUpdateSchema.model_rebuild()
AppSettingsReadSchema.model_rebuild()
AppSettingsUpdateSchema.model_rebuild()
AppSettingHistoryItemSchema.model_rebuild()
BaseModelSchema.model_rebuild()
BatchItem.model_rebuild()
BodyCreateFolderStorageFolderCreatePost.model_rebuild()
BodyGetColumnsUtilsCsvGetColumnsPost.model_rebuild()
BodySqlCodeMetadataUtilsSqlCodeMetadataPost.model_rebuild()
BodyUploadFileViaGatewayStorageUploadFilePost.model_rebuild()
BrokenConnectionReadResponse.model_rebuild()
ClearProjectCacheRequest.model_rebuild()
ClearProjectCacheResponse.model_rebuild()
ClearProjectDataCacheRequest.model_rebuild()
ClearProjectDataCacheResponse.model_rebuild()
ClearProjectMetadataCacheRequest.model_rebuild()
ClearProjectMetadataCacheResponse.model_rebuild()
ClickHouseEngineSpec.model_rebuild()
ClickhouseSqlHttpConnectionCreateRequest.model_rebuild()
ClickhouseSqlHttpConnectionReadResponse.model_rebuild()
ClickhouseSqlHttpConnectionUpdateRequest.model_rebuild()
ClickhouseSqlNativeDefaultDriverConnectionCreateRequest.model_rebuild()
ClickhouseSqlNativeDefaultDriverConnectionReadResponse.model_rebuild()
ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest.model_rebuild()
Column.model_rebuild()
CommonResponse.model_rebuild()
ConnectionCheckResult.model_rebuild()
ConnectionDriverInfoResponse.model_rebuild()
ConnectionIssueResponse.model_rebuild()
ConnectionKindInfoResponse.model_rebuild()
ConnectionTypeInfoResponse.model_rebuild()
CreateDatabaseRequest.model_rebuild()
CreateSchemaRequest.model_rebuild()
CreateTableFromSQLRequest.model_rebuild()
CreateTableFromSchemaRequest.model_rebuild()
DBColumn.model_rebuild()
DBDatabase.model_rebuild()
DBMetadata.model_rebuild()
DBSchema.model_rebuild()
DBTable.model_rebuild()
DTypeMetadata.model_rebuild()
DataFrameData.model_rebuild()
DataFrameMetadataInput.model_rebuild()
DataFrameMetadataOutput.model_rebuild()
DeleteFilesIn.model_rebuild()
DeleteFolderIn.model_rebuild()
EnvironmentFilterDefinition.model_rebuild()
EnvironmentGlobalDefinition.model_rebuild()
EnvironmentTestDefinition.model_rebuild()
ErrorResponse.model_rebuild()
ExpressionPolicy.model_rebuild()
ExpressionsConfig.model_rebuild()
ExtensionFrontendReadSchema.model_rebuild()
ExtensionManifestBackendSchema.model_rebuild()
ExtensionManifestFrontendSchema.model_rebuild()
ExtensionManifestNodeSchema.model_rebuild()
ExtensionManifestSchema.model_rebuild()
ExtensionReadSchema.model_rebuild()
ExtensionStateReadSchema.model_rebuild()
ExtensionStateUpdateSchema.model_rebuild()
FTPFile.model_rebuild()
FTPFolder.model_rebuild()
FTPProperties.model_rebuild()
FTPSecrets.model_rebuild()
ForeignKeySpec.model_rebuild()
FtpFileNoDriverConnectionCreateRequest.model_rebuild()
FtpFileNoDriverConnectionReadResponse.model_rebuild()
FtpFileNoDriverConnectionUpdateRequest.model_rebuild()
GenerateSchemaDDLRequest.model_rebuild()
GenerateSchemaDDLResponse.model_rebuild()
GenerateTableDDL.model_rebuild()
GenerateTableDDLResponse.model_rebuild()
GraphEdgeUISchema.model_rebuild()
GraphEdgeUpdateUISchema.model_rebuild()
GraphNodeData.model_rebuild()
GraphNodeDataUpdate.model_rebuild()
GraphNodeUISchemaInput.model_rebuild()
GraphNodeUISchemaOutput.model_rebuild()
GraphNodeUIUpdateSchema.model_rebuild()
GraphOperationResponse.model_rebuild()
GraphOperationsAggregated.model_rebuild()
HTTPValidationError.model_rebuild()
IndexSpec.model_rebuild()
InputDefinitionModel.model_rebuild()
JSONData.model_rebuild()
KafkaProperties.model_rebuild()
KafkaQueueNoDriverConnectionCreateRequest.model_rebuild()
KafkaQueueNoDriverConnectionReadResponse.model_rebuild()
KafkaQueueNoDriverConnectionUpdateRequest.model_rebuild()
KafkaSecrets.model_rebuild()
LicenseActivationSchema.model_rebuild()
LicenseStatusSchema.model_rebuild()
LogEntriesPageSchema.model_rebuild()
LogEntrySchema.model_rebuild()
MongodbSqlNoDriverConnectionCreateRequest.model_rebuild()
MongodbSqlNoDriverConnectionReadResponse.model_rebuild()
MongodbSqlNoDriverConnectionUpdateRequest.model_rebuild()
MSSQLNamedInstanceProperties.model_rebuild()
MSSQLTCPProperties.model_rebuild()
MovePathIn.model_rebuild()
MssqlSqlAioodbcConnectionCreateRequest.model_rebuild()
MssqlSqlAioodbcConnectionReadResponse.model_rebuild()
MssqlSqlAioodbcConnectionUpdateRequest.model_rebuild()
MssqlSqlPyodbcDefaultDriverConnectionCreateRequest.model_rebuild()
MssqlSqlPyodbcDefaultDriverConnectionReadResponse.model_rebuild()
MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest.model_rebuild()
MysqlSqlAiomysqlConnectionCreateRequest.model_rebuild()
MysqlSqlAiomysqlConnectionReadResponse.model_rebuild()
MysqlSqlAiomysqlConnectionUpdateRequest.model_rebuild()
MysqlSqlPymysqlDefaultDriverConnectionCreateRequest.model_rebuild()
MysqlSqlPymysqlDefaultDriverConnectionReadResponse.model_rebuild()
MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest.model_rebuild()
NodeDefinition.model_rebuild()
NodeInputConstantValue.model_rebuild()
NodeInputExpressionValue.model_rebuild()
NodeInputLinkValue.model_rebuild()
ODBCDriverOptionsInput.model_rebuild()
ODBCDriverOptionsOutput.model_rebuild()
OOMGuardConfig.model_rebuild()
OracleSqlOracledbDefaultDriverConnectionCreateRequest.model_rebuild()
OracleSqlOracledbDefaultDriverConnectionReadResponse.model_rebuild()
OracleSqlOracledbDefaultDriverConnectionUpdateRequest.model_rebuild()
OrganizationCreateSchema.model_rebuild()
OrganizationReadSchema.model_rebuild()
OrganizationUpdateSchema.model_rebuild()
OutputDefinitionModel.model_rebuild()
Position.model_rebuild()
PostgresSqlAsyncpgConnectionCreateRequest.model_rebuild()
PostgresSqlAsyncpgConnectionReadResponse.model_rebuild()
PostgresSqlAsyncpgConnectionUpdateRequest.model_rebuild()
PostgresSqlPsycopg2ConnectionCreateRequest.model_rebuild()
PostgresSqlPsycopg2ConnectionReadResponse.model_rebuild()
PostgresSqlPsycopg2ConnectionUpdateRequest.model_rebuild()
PostgresSqlPsycopgDefaultDriverConnectionCreateRequest.model_rebuild()
PostgresSqlPsycopgDefaultDriverConnectionReadResponse.model_rebuild()
PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest.model_rebuild()
PresignedPostOut.model_rebuild()
ProjectCreateSchema.model_rebuild()
ProjectFolderCreateSchema.model_rebuild()
ProjectFolderItemSchema.model_rebuild()
ProjectFolderReadSchema.model_rebuild()
ProjectFolderUpdateSchema.model_rebuild()
ProjectItemsPageSchema.model_rebuild()
ProjectLastRunSchema.model_rebuild()
ProjectReadSchema.model_rebuild()
ProjectSchedulePatchRequest.model_rebuild()
ProjectScheduleRequest.model_rebuild()
ProjectScheduleResponse.model_rebuild()
ProjectScheduleRunResponse.model_rebuild()
ProjectSearchPageSchema.model_rebuild()
ProjectUpdateSchema.model_rebuild()
ProjectVariableBase.model_rebuild()
ProjectVariableCreate.model_rebuild()
ProjectVariableRead.model_rebuild()
ProjectVariableUpdate.model_rebuild()
ProjectVariablesBulkUpdate.model_rebuild()
ProjectsDeleteSchema.model_rebuild()
PytestEntityListResponse.model_rebuild()
PytestEntityLocation.model_rebuild()
PytestEntitySchema.model_rebuild()
QueueActionRequest.model_rebuild()
QueueActionResponse.model_rebuild()
QueueStateResponse.model_rebuild()
QueueTask.model_rebuild()
QueueTopicCreateSchema.model_rebuild()
QueueTopicDataSchema.model_rebuild()
QueueTopicDataSuccessSchema.model_rebuild()
QueueTopicReadSchema.model_rebuild()
QueueTopicUpdateSchema.model_rebuild()
RenamePathIn.model_rebuild()
RuntimeConfig.model_rebuild()
RuntimeConfigFeatures.model_rebuild()
S3File.model_rebuild()
S3FileNoDriverConnectionCreateRequest.model_rebuild()
S3FileNoDriverConnectionReadResponse.model_rebuild()
S3FileNoDriverConnectionUpdateRequest.model_rebuild()
S3Folder.model_rebuild()
S3Properties.model_rebuild()
S3Secrets.model_rebuild()
SFTPProperties.model_rebuild()
SFTPSecrets.model_rebuild()
SMBProtocolProperties.model_rebuild()
SMBProtocolSecrets.model_rebuild()
SQLCodeMetadata.model_rebuild()
SQLProperties.model_rebuild()
SQLSecrets.model_rebuild()
SQLStatementMetadata.model_rebuild()
ScheduleResponse.model_rebuild()
ServicesStatus.model_rebuild()
SetupStatus.model_rebuild()
SetupStep.model_rebuild()
SetupStepField.model_rebuild()
SetupStepSubmitRequest.model_rebuild()
SftpFileNoDriverConnectionCreateRequest.model_rebuild()
SftpFileNoDriverConnectionReadResponse.model_rebuild()
SftpFileNoDriverConnectionUpdateRequest.model_rebuild()
SmbprotocolFileNoDriverConnectionCreateRequest.model_rebuild()
SmbprotocolFileNoDriverConnectionReadResponse.model_rebuild()
SmbprotocolFileNoDriverConnectionUpdateRequest.model_rebuild()
SubgraphData.model_rebuild()
SubgraphDataUpdate.model_rebuild()
SubgraphUISchema.model_rebuild()
SubgraphUIUpdateSchema.model_rebuild()
SystemInfo.model_rebuild()
SystemVariableDefinitionModel.model_rebuild()
TableCreateSpec.model_rebuild()
TaskInfo.model_rebuild()
TaskResponse.model_rebuild()
UserFileTreeSchema.model_rebuild()
UserReadSchema.model_rebuild()
ValidationError.model_rebuild()
VersionInfo.model_rebuild()
WorkerSystemInfo.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel1.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel2.model_rebuild()
AdminUserCreate.model_rebuild()
AdminUserUpdate.model_rebuild()
ApiTokenCreate.model_rebuild()
ApiTokenCreatedData.model_rebuild()
ApiTokensListData.model_rebuild()
AuthenticatedData.model_rebuild()
CommonDataNextStepResponseManagedUserData.model_rebuild()
CommonDataResponseApiTokenCreatedData.model_rebuild()
CommonDataResponseApiTokenEmptyData.model_rebuild()
CommonDataResponseApiTokensListData.model_rebuild()
CommonDataResponseAuthenticatedData.model_rebuild()
CommonDataResponseManagedUserData.model_rebuild()
CommonDataResponseUserProfileData.model_rebuild()
ManagedUserData.model_rebuild()
UserLogin.model_rebuild()
UserProfileData.model_rebuild()
UserTokenRead.model_rebuild()
DataFrameMetadata.model_rebuild()
FTPDirectoryMetadata.model_rebuild()
FTPMetadata.model_rebuild()
JSONFlattenCandidate.model_rebuild()
JSONMetadata.model_rebuild()
JSONStructureNode.model_rebuild()
JSONStructureStats.model_rebuild()
KafkaBroker.model_rebuild()
KafkaCluster.model_rebuild()
KafkaMetadata.model_rebuild()
KafkaTopic.model_rebuild()
LogEvent.model_rebuild()
NodeExecutionStatusEvent.model_rebuild()
NodeMetadataEvent.model_rebuild()
PingEvent.model_rebuild()
ProgressEvent.model_rebuild()
S3Bucket.model_rebuild()
S3Metadata.model_rebuild()
SMBDirectoryMetadata.model_rebuild()
SMBFile.model_rebuild()
SMBFolder.model_rebuild()
SMBMetadata.model_rebuild()
SeriesMetadata.model_rebuild()
StatusUpdateEvent.model_rebuild()
TaskError.model_rebuild()
TaskExecutionStatusEvent.model_rebuild()
TaskExecutionTelemetryEvent.model_rebuild()
VariableDescriptorMetadata.model_rebuild()
VariableMapMetadata.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel10.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel11.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel12.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel13.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel14.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel15.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel16.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel17.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel18.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel19.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel20.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel21.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel22.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel23.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel24.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel25.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel26.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel27.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel28.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel29.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel3.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel30.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel31.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel32.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel33.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel34.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel35.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel36.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel37.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel38.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel39.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel4.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel40.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel41.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel42.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel43.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel44.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel45.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel46.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel47.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel48.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel49.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel5.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel50.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel51.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel52.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel53.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel54.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel55.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel56.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel57.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel58.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel59.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel6.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel60.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel61.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel62.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel63.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel64.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel65.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel66.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel67.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel68.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel69.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel7.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel70.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel71.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel72.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel73.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel74.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel75.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel76.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel77.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel78.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel79.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel8.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel80.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel81.model_rebuild()
SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel9.model_rebuild()
GraphNodeUISchema.model_rebuild()
ODBCDriverOptions.model_rebuild()


__all__ = [
    'SDKBaseModel',
    'AIAnalysisCreateResponseSchema',
    'AIAnalysisCreateSchema',
    'AIAnalysisHistoryItemSchema',
    'AIAnalysisHistoryResponseSchema',
    'AIAnalysisReadSchema',
    'AIAnalysisStatus',
    'AIServiceAnalysisClassification',
    'AIServiceAnalysisResultSchema',
    'AIServiceAnalysisSeverity',
    'AIServiceRecommendedActionSchema',
    'AIServiceSourceContextItemSchema',
    'AdminUserCreateSchema',
    'AdminUserReadSchema',
    'AdminUserUpdateSchema',
    'AppSettingsDccReadSchema',
    'AppSettingsDccUpdateSchema',
    'AppSettingsLicenseReadSchema',
    'AppSettingsLicenseUpdateSchema',
    'AppSettingsRuntimeReadSchema',
    'AppSettingsRuntimeUpdateSchema',
    'AppSettingsReadSchema',
    'AppSettingsUpdateSchema',
    'AppSettingHistoryItemSchema',
    'BaseModelSchema',
    'BatchItem',
    'BodyCreateFolderStorageFolderCreatePost',
    'BodyGetColumnsUtilsCsvGetColumnsPost',
    'BodySqlCodeMetadataUtilsSqlCodeMetadataPost',
    'BodyUploadFileViaGatewayStorageUploadFilePost',
    'BrokenConnectionReadResponse',
    'ClearProjectCacheRequest',
    'ClearProjectCacheResponse',
    'ClearProjectDataCacheRequest',
    'ClearProjectDataCacheResponse',
    'ClearProjectMetadataCacheRequest',
    'ClearProjectMetadataCacheResponse',
    'ClickHouseEngineSpec',
    'ClickhouseSqlHttpConnectionCreateRequest',
    'ClickhouseSqlHttpConnectionReadResponse',
    'ClickhouseSqlHttpConnectionUpdateRequest',
    'ClickhouseSqlNativeDefaultDriverConnectionCreateRequest',
    'ClickhouseSqlNativeDefaultDriverConnectionReadResponse',
    'ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest',
    'Column',
    'CommonResponse',
    'ConnectionCheckResult',
    'ConnectionDriverInfoResponse',
    'ConnectionIssueResponse',
    'ConnectionKindInfoResponse',
    'ConnectionTypeInfoResponse',
    'CreateDatabaseRequest',
    'CreateSchemaRequest',
    'CreateTableFromSQLRequest',
    'CreateTableFromSchemaRequest',
    'DBColumn',
    'DBDatabase',
    'DBMetadata',
    'DBSchema',
    'DBTable',
    'DBTableType',
    'DTypeMetadata',
    'DVTDefaultRoles',
    'DataFrameData',
    'DataFrameMetadataInput',
    'DataFrameMetadataOutput',
    'DataType',
    'DeleteFilesIn',
    'DeleteFolderIn',
    'EnvironmentFilterDefinition',
    'EnvironmentGlobalDefinition',
    'EnvironmentTestDefinition',
    'ErrorResponse',
    'ExceptionCategory',
    'PipelineExecutionMode',
    'ExpressionPolicy',
    'ExpressionsConfig',
    'ExtensionDepsStatus',
    'ExtensionFrontendReadSchema',
    'ExtensionLicenseStatus',
    'ExtensionManifestBackendSchema',
    'ExtensionManifestFrontendSchema',
    'ExtensionManifestNodeSchema',
    'ExtensionManifestSchema',
    'ExtensionReadSchema',
    'ExtensionStateReadSchema',
    'ExtensionStateUpdateSchema',
    'FTPFile',
    'FTPFolder',
    'FTPMode',
    'FTPProperties',
    'FTPSecrets',
    'ForeignKeySpec',
    'FtpFileNoDriverConnectionCreateRequest',
    'FtpFileNoDriverConnectionReadResponse',
    'FtpFileNoDriverConnectionUpdateRequest',
    'GenerateSchemaDDLRequest',
    'GenerateSchemaDDLResponse',
    'GenerateTableDDL',
    'GenerateTableDDLResponse',
    'GraphEdgeUISchema',
    'GraphEdgeUpdateUISchema',
    'GraphNodeData',
    'GraphNodeDataUpdate',
    'GraphNodeUISchemaInput',
    'GraphNodeUISchemaOutput',
    'GraphNodeUIUpdateSchema',
    'GraphOperationResponse',
    'GraphOperationsAggregated',
    'HTTPValidationError',
    'IO',
    'IndexSpec',
    'InputDefinitionModel',
    'JSONData',
    'KafkaProperties',
    'KafkaQueueNoDriverConnectionCreateRequest',
    'KafkaQueueNoDriverConnectionReadResponse',
    'KafkaQueueNoDriverConnectionUpdateRequest',
    'KafkaSecrets',
    'LicenseActivationSchema',
    'LicenseStatusSchema',
    'LogEntriesPageSchema',
    'LogEntrySchema',
    'MongodbSqlNoDriverConnectionCreateRequest',
    'MongodbSqlNoDriverConnectionReadResponse',
    'MongodbSqlNoDriverConnectionUpdateRequest',
    'MSSQLNamedInstanceProperties',
    'MSSQLProperties',
    'MSSQLTCPProperties',
    'MovePathIn',
    'MssqlSqlAioodbcConnectionCreateRequest',
    'MssqlSqlAioodbcConnectionReadResponse',
    'MssqlSqlAioodbcConnectionUpdateRequest',
    'MssqlSqlPyodbcDefaultDriverConnectionCreateRequest',
    'MssqlSqlPyodbcDefaultDriverConnectionReadResponse',
    'MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest',
    'MysqlSqlAiomysqlConnectionCreateRequest',
    'MysqlSqlAiomysqlConnectionReadResponse',
    'MysqlSqlAiomysqlConnectionUpdateRequest',
    'MysqlSqlPymysqlDefaultDriverConnectionCreateRequest',
    'MysqlSqlPymysqlDefaultDriverConnectionReadResponse',
    'MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest',
    'NoDriverOptions',
    'NodeDefinition',
    'NodeInputConstantValue',
    'NodeInputExpressionValue',
    'NodeInputLinkValue',
    'NodeType',
    'ODBCDriverOptionsInput',
    'ODBCDriverOptionsOutput',
    'OOMGuardMode',
    'OOMGuardConfig',
    'OOMWorkerThresholdType',
    'OracleSqlOracledbDefaultDriverConnectionCreateRequest',
    'OracleSqlOracledbDefaultDriverConnectionReadResponse',
    'OracleSqlOracledbDefaultDriverConnectionUpdateRequest',
    'OrganizationCreateSchema',
    'OrganizationReadSchema',
    'OrganizationUpdateSchema',
    'OutputDefinitionModel',
    'Position',
    'PostgresSqlAsyncpgConnectionCreateRequest',
    'PostgresSqlAsyncpgConnectionReadResponse',
    'PostgresSqlAsyncpgConnectionUpdateRequest',
    'PostgresSqlPsycopg2ConnectionCreateRequest',
    'PostgresSqlPsycopg2ConnectionReadResponse',
    'PostgresSqlPsycopg2ConnectionUpdateRequest',
    'PostgresSqlPsycopgDefaultDriverConnectionCreateRequest',
    'PostgresSqlPsycopgDefaultDriverConnectionReadResponse',
    'PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest',
    'PresignedPostOut',
    'ProjectCreateSchema',
    'ProjectFolderCreateSchema',
    'ProjectFolderItemSchema',
    'ProjectFolderReadSchema',
    'ProjectFolderUpdateSchema',
    'ProjectItemsPageSchema',
    'ProjectLastRunSchema',
    'ProjectReadSchema',
    'ProjectSchedulePatchRequest',
    'ProjectScheduleRequest',
    'ProjectScheduleResponse',
    'ProjectScheduleRunResponse',
    'ProjectSearchPageSchema',
    'ProjectUpdateSchema',
    'ProjectVariableBase',
    'ProjectVariableCreate',
    'ProjectVariableRead',
    'ProjectVariableUpdate',
    'ProjectVariablesBulkUpdate',
    'ProjectsDeleteSchema',
    'PytestEntityListResponse',
    'PytestEntityLocation',
    'PytestEntitySchema',
    'QueueAction',
    'QueueActionRequest',
    'QueueActionResponse',
    'QueueStateResponse',
    'QueueTask',
    'QueueTopicCreateSchema',
    'QueueTopicDataSchema',
    'QueueTopicDataSuccessSchema',
    'QueueTopicReadSchema',
    'QueueTopicUpdateSchema',
    'RenamePathIn',
    'RuntimeConfig',
    'RuntimeConfigFeatures',
    'S3File',
    'S3FileNoDriverConnectionCreateRequest',
    'S3FileNoDriverConnectionReadResponse',
    'S3FileNoDriverConnectionUpdateRequest',
    'S3Folder',
    'S3Properties',
    'S3Secrets',
    'SFTPProperties',
    'SFTPSecrets',
    'SMBProtocolProperties',
    'SMBProtocolSecrets',
    'SQLCodeMetadata',
    'SQLProperties',
    'SQLSecrets',
    'SQLStatementMetadata',
    'ScheduleResponse',
    'ServicesStatus',
    'SetupStatus',
    'SetupStep',
    'SetupStepField',
    'SetupStepSubmitRequest',
    'SftpFileNoDriverConnectionCreateRequest',
    'SftpFileNoDriverConnectionReadResponse',
    'SftpFileNoDriverConnectionUpdateRequest',
    'SmbprotocolFileNoDriverConnectionCreateRequest',
    'SmbprotocolFileNoDriverConnectionReadResponse',
    'SmbprotocolFileNoDriverConnectionUpdateRequest',
    'SubgraphData',
    'SubgraphDataUpdate',
    'SubgraphUISchema',
    'SubgraphUIUpdateSchema',
    'SystemInfo',
    'SystemVariableDefinitionModel',
    'TableCreateSpec',
    'TaskInfo',
    'TaskResponse',
    'TaskSource',
    'TaskStatus',
    'UserFileTreeSchema',
    'UserReadSchema',
    'ValidationError',
    'VersionInfo',
    'WorkerStatus',
    'WorkerSystemInfo',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel1',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel2',
    'AdminUserCreate',
    'AdminUserUpdate',
    'ApiTokenCreate',
    'ApiTokenCreatedData',
    'ApiTokenEmptyData',
    'ApiTokensListData',
    'AuthenticatedData',
    'CommonDataNextStepResponseManagedUserData',
    'CommonDataResponseApiTokenCreatedData',
    'CommonDataResponseApiTokenEmptyData',
    'CommonDataResponseApiTokensListData',
    'CommonDataResponseAuthenticatedData',
    'CommonDataResponseManagedUserData',
    'CommonDataResponseUserProfileData',
    'ManagedUserData',
    'UserLogin',
    'UserProfileData',
    'UserTokenRead',
    'Event',
    'DataFrameMetadata',
    'ExecutionStatus',
    'FTPDirectoryMetadata',
    'FTPMetadata',
    'JSONFlattenCandidate',
    'JSONFlattenCandidateKind',
    'JSONMetadata',
    'JSONNodeKind',
    'JSONStructureNode',
    'JSONStructureStats',
    'KafkaBroker',
    'KafkaCluster',
    'KafkaMetadata',
    'KafkaTopic',
    'LogEvent',
    'NodeExecutionStatusEvent',
    'NodeMetadataEvent',
    'PingEvent',
    'ProgressEvent',
    'S3Bucket',
    'S3Metadata',
    'SMBDirectoryMetadata',
    'SMBFile',
    'SMBFolder',
    'SMBMetadata',
    'SeriesMetadata',
    'StatusUpdateEvent',
    'TaskError',
    'TaskExecutionStatusEvent',
    'TaskExecutionTelemetryEvent',
    'BaseVariableDefinitionModel',
    'VariableDescriptorMetadata',
    'VariableMapMetadata',
    'DBDialect',
    'Metadata',
    'NodeOutputMetadata',
    'NodeMetadata',
    'PipelineMetadata',
    'EventType',
    'RegisteredException',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel10',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel11',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel12',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel13',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel14',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel15',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel16',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel17',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel18',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel19',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel20',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel21',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel22',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel23',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel24',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel25',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel26',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel27',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel28',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel29',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel3',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel30',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel31',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel32',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel33',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel34',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel35',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel36',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel37',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel38',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel39',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel4',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel40',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel41',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel42',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel43',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel44',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel45',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel46',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel47',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel48',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel49',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel5',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel50',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel51',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel52',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel53',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel54',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel55',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel56',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel57',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel58',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel59',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel6',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel60',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel61',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel62',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel63',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel64',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel65',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel66',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel67',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel68',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel69',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel7',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel70',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel71',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel72',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel73',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel74',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel75',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel76',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel77',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel78',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel79',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel8',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel80',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel81',
    'SrcExceptionRegistryRegisteredExceptionRegisteredExceptionInitSubclassLocalsModel9',
    'LiteralInputDefinitionKey',
    'LiteralOutputDefinitionKey',
    'InputDefinitionKey',
    'OutputDefinitionKey',
    'NodeInputValue',
    'NodeInputValues',
    'GraphNodeUISchema',
    'DBConnectionCreateV1',
    'ODBCDriverOptions',
    'DBConnectionReadV1',
    'DBConnectionUpdateV1',
    'ConnectionKindV1',
    'ConnectionTypeV1'
]

from __future__ import annotations

from typing import Any

from src.clients.gateway_sdk.generated.models import *  # noqa: F403
from src.clients.gateway_sdk.models_extra import BinaryPayload, FileUpload, open_file_upload
from src.clients.gateway_sdk.resources.base import AsyncResourceBase


class AsyncAdminResource(AsyncResourceBase):
    users: AsyncAdminUsersResource

class AsyncAppSettingsResource(AsyncResourceBase):
    fields: AsyncAppSettingsFieldsResource

    async def create(self, *, key: str, validate: bool | None = False, data: Any | dict) -> Any:
        return await self._request_json(
            method='POST',
            path='/app-settings/{key}',
            path_params={'key': key},
            query={'validate': validate},
            data=data,
            response_type=Any,
        )

    async def delete(self, *, key: str) -> Any:
        return await self._request_json(
            method='DELETE',
            path='/app-settings/{key}',
            path_params={'key': key},
            response_type=Any,
        )

    async def history(self, *, key: str) -> list[AppSettingHistoryItemSchema]:
        return await self._request_json(
            method='GET',
            path='/app-settings/{key}/history',
            path_params={'key': key},
            response_type=list[AppSettingHistoryItemSchema],
        )

    async def list(self, *, validate: bool | None = False) -> AppSettingsReadSchema:
        return await self._request_json(
            method='GET',
            path='/app-settings',
            query={'validate': validate},
            response_type=AppSettingsReadSchema,
        )

    async def retrieve(self, *, key: str, validate: bool | None = False) -> Any:
        return await self._request_json(
            method='GET',
            path='/app-settings/{key}',
            path_params={'key': key},
            query={'validate': validate},
            response_type=Any,
        )

    async def set(self, *, validate: bool | None = False, data: AppSettingsUpdateSchema | dict) -> AppSettingsReadSchema:
        return await self._request_json(
            method='POST',
            path='/app-settings',
            query={'validate': validate},
            data=data,
            response_type=AppSettingsReadSchema,
        )

class AsyncConfigResource(AsyncResourceBase):
    async def expressions(self) -> ExpressionsConfig:
        return await self._request_json(
            method='GET',
            path='/config/expressions',
            response_type=ExpressionsConfig,
        )

class AsyncDbConnectionsResource(AsyncResourceBase):
    async def check(self, *, data: ClickhouseSqlNativeDefaultDriverConnectionCreateRequest | ClickhouseSqlHttpConnectionCreateRequest | FtpFileNoDriverConnectionCreateRequest | KafkaQueueNoDriverConnectionCreateRequest | MongodbSqlNoDriverConnectionCreateRequest | MssqlSqlPyodbcDefaultDriverConnectionCreateRequest | MssqlSqlAioodbcConnectionCreateRequest | MysqlSqlPymysqlDefaultDriverConnectionCreateRequest | MysqlSqlAiomysqlConnectionCreateRequest | OracleSqlOracledbDefaultDriverConnectionCreateRequest | PostgresSqlPsycopgDefaultDriverConnectionCreateRequest | PostgresSqlPsycopg2ConnectionCreateRequest | PostgresSqlAsyncpgConnectionCreateRequest | S3FileNoDriverConnectionCreateRequest | SftpFileNoDriverConnectionCreateRequest | SmbprotocolFileNoDriverConnectionCreateRequest | dict) -> ConnectionCheckResult:
        return await self._request_json(
            method='POST',
            path='/db-connections/check',
            data=data,
            response_type=ConnectionCheckResult,
        )

    async def check_by_id(self, *, connection_id: str, data: ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest | ClickhouseSqlHttpConnectionUpdateRequest | FtpFileNoDriverConnectionUpdateRequest | KafkaQueueNoDriverConnectionUpdateRequest | MongodbSqlNoDriverConnectionUpdateRequest | MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest | MssqlSqlAioodbcConnectionUpdateRequest | MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest | MysqlSqlAiomysqlConnectionUpdateRequest | OracleSqlOracledbDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopg2ConnectionUpdateRequest | PostgresSqlAsyncpgConnectionUpdateRequest | S3FileNoDriverConnectionUpdateRequest | SftpFileNoDriverConnectionUpdateRequest | SmbprotocolFileNoDriverConnectionUpdateRequest | None | dict | None = None) -> ConnectionCheckResult:
        return await self._request_json(
            method='POST',
            path='/db-connections/{connection_id}/check',
            path_params={'connection_id': connection_id},
            data=data,
            response_type=ConnectionCheckResult,
        )

    async def create(self, *, data: ClickhouseSqlNativeDefaultDriverConnectionCreateRequest | ClickhouseSqlHttpConnectionCreateRequest | FtpFileNoDriverConnectionCreateRequest | KafkaQueueNoDriverConnectionCreateRequest | MongodbSqlNoDriverConnectionCreateRequest | MssqlSqlPyodbcDefaultDriverConnectionCreateRequest | MssqlSqlAioodbcConnectionCreateRequest | MysqlSqlPymysqlDefaultDriverConnectionCreateRequest | MysqlSqlAiomysqlConnectionCreateRequest | OracleSqlOracledbDefaultDriverConnectionCreateRequest | PostgresSqlPsycopgDefaultDriverConnectionCreateRequest | PostgresSqlPsycopg2ConnectionCreateRequest | PostgresSqlAsyncpgConnectionCreateRequest | S3FileNoDriverConnectionCreateRequest | SftpFileNoDriverConnectionCreateRequest | SmbprotocolFileNoDriverConnectionCreateRequest | dict) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse:
        return await self._request_json(
            method='POST',
            path='/db-connections',
            data=data,
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse,
        )

    async def delete(self, *, id: str) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='DELETE',
            path='/db-connections/{connection_id}',
            path_params={'connection_id': id},
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

    async def kinds(self) -> list[ConnectionKindInfoResponse]:
        return await self._request_json(
            method='GET',
            path='/db-connections/kinds',
            response_type=list[ConnectionKindInfoResponse],
        )

    async def list(self, *, kind: Literal['file', 'queue', 'sql'] | str | None = None, type: Literal['clickhouse', 'ftp', 'kafka', 'mongodb', 'mssql', 'mysql', 'oracle', 'postgres', 's3', 'sftp', 'smbprotocol'] | str | None = None, name: str | None = None, labels: str | None = None, metadata: str | None = None, extra: str | None = None) -> list[ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse]:
        return await self._request_json(
            method='GET',
            path='/db-connections',
            query={'kind': kind, 'type': type, 'name': name, 'labels': labels, 'metadata': metadata, 'extra': extra},
            response_type=list[ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse],
        )

    async def retrieve(self, *, id: str) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='GET',
            path='/db-connections/{connection_id}',
            path_params={'connection_id': id},
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

    async def types(self) -> list[ConnectionTypeInfoResponse]:
        return await self._request_json(
            method='GET',
            path='/db-connections/types',
            response_type=list[ConnectionTypeInfoResponse],
        )

    async def update(self, *, id: str, data: ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest | ClickhouseSqlHttpConnectionUpdateRequest | FtpFileNoDriverConnectionUpdateRequest | KafkaQueueNoDriverConnectionUpdateRequest | MongodbSqlNoDriverConnectionUpdateRequest | MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest | MssqlSqlAioodbcConnectionUpdateRequest | MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest | MysqlSqlAiomysqlConnectionUpdateRequest | OracleSqlOracledbDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopg2ConnectionUpdateRequest | PostgresSqlAsyncpgConnectionUpdateRequest | S3FileNoDriverConnectionUpdateRequest | SftpFileNoDriverConnectionUpdateRequest | SmbprotocolFileNoDriverConnectionUpdateRequest | dict) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='PATCH',
            path='/db-connections/{connection_id}',
            path_params={'connection_id': id},
            data=data,
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

class AsyncExceptionsResource(AsyncResourceBase):
    async def delete_exception(self, *, name: str, code: str) -> dict[str, Any]:
        return await self._request_json(
            method='POST',
            path='/exceptions/delete_exception',
            query={'name': name, 'code': code},
            response_type=dict[str, Any],
        )

    async def list(self, *, name: str | None = None, code: str | None = None, description: str | None = None, category: ExceptionCategory | None = None) -> dict[str, Any]:
        return await self._request_json(
            method='GET',
            path='/exceptions/',
            query={'name': name, 'code': code, 'description': description, 'category': category},
            response_type=dict[str, Any],
        )

    async def register_exception(self, *, name: str, code: str, description: str, category: ExceptionCategory) -> dict[str, Any]:
        return await self._request_json(
            method='POST',
            path='/exceptions/register_exception',
            query={'name': name, 'code': code, 'description': description, 'category': category},
            response_type=dict[str, Any],
        )

class AsyncExtensionsResource(AsyncResourceBase):
    frontend: AsyncExtensionsFrontendResource
    state: AsyncExtensionsStateResource

    async def activate_license(self, *, extension_name: str, data: LicenseActivationSchema | dict) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/activate-license',
            path_params={'extension_name': extension_name},
            data=data,
            response_type=ExtensionReadSchema,
        )

    async def deactivate_license(self, *, extension_name: str) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/deactivate-license',
            path_params={'extension_name': extension_name},
            response_type=ExtensionReadSchema,
        )

    async def disable(self, *, extension_name: str) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/disable',
            path_params={'extension_name': extension_name},
            response_type=ExtensionReadSchema,
        )

    async def enable(self, *, extension_name: str) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/enable',
            path_params={'extension_name': extension_name},
            response_type=ExtensionReadSchema,
        )

    async def install(self, *, extension_name: str, version: str | None = None) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/install',
            path_params={'extension_name': extension_name},
            query={'version': version},
            response_type=ExtensionReadSchema,
        )

    async def license_status(self, *, extension_name: str) -> LicenseStatusSchema:
        return await self._request_json(
            method='GET',
            path='/extensions/{extension_name}/license-status',
            path_params={'extension_name': extension_name},
            response_type=LicenseStatusSchema,
        )

    async def list(self) -> list[ExtensionReadSchema]:
        return await self._request_json(
            method='GET',
            path='/extensions',
            response_type=list[ExtensionReadSchema],
        )

    async def reload(self, *, extension_name: str) -> ExtensionReadSchema:
        return await self._request_json(
            method='POST',
            path='/extensions/{extension_name}/reload',
            path_params={'extension_name': extension_name},
            response_type=ExtensionReadSchema,
        )

    async def reload_installed(self) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/extensions/reload-installed',
            response_type=CommonResponse,
        )

    async def sync(self) -> list[ExtensionReadSchema]:
        return await self._request_json(
            method='POST',
            path='/extensions/sync',
            response_type=list[ExtensionReadSchema],
        )

    async def uninstall(self, *, extension_name: str) -> ExtensionReadSchema:
        return await self._request_json(
            method='DELETE',
            path='/extensions/{extension_name}/uninstall',
            path_params={'extension_name': extension_name},
            response_type=ExtensionReadSchema,
        )

class AsyncLogsResource(AsyncResourceBase):
    async def get(self) -> str:
        return await self._request_text(
            method='GET',
            path='/logs/',
        )

class AsyncMetricsResource(AsyncResourceBase):
    async def retrieve(self) -> dict[str, Any]:
        return await self._request_json(
            method='GET',
            path='/metrics',
            response_type=dict[str, Any],
        )

class AsyncNodesResource(AsyncResourceBase):
    async def base_variable_definitions(self) -> dict[str, BaseVariableDefinitionModel]:
        return await self._request_json(
            method='GET',
            path='/nodes/base-variable-definitions',
            response_type=dict[str, BaseVariableDefinitionModel],
        )

    async def list(self, *, x_language: str | None = None, accept_language: str | None = None) -> dict[str, NodeDefinition]:
        return await self._request_json(
            method='GET',
            path='/nodes/',
            headers={'x-language': x_language, 'accept-language': accept_language},
            response_type=dict[str, NodeDefinition],
        )

    async def retrieve(self, *, node_name: str, x_language: str | None = None, accept_language: str | None = None) -> NodeDefinition:
        return await self._request_json(
            method='GET',
            path='/nodes/{node_name}',
            path_params={'node_name': node_name},
            headers={'x-language': x_language, 'accept-language': accept_language},
            response_type=NodeDefinition,
        )

class AsyncOrganizationsResource(AsyncResourceBase):
    async def create(self, *, data: OrganizationCreateSchema | dict) -> OrganizationReadSchema:
        return await self._request_json(
            method='POST',
            path='/organizations',
            data=data,
            response_type=OrganizationReadSchema,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/organizations/{organization_id}',
            path_params={'organization_id': id},
            response_type=CommonResponse,
        )

    async def list(self) -> list[OrganizationReadSchema]:
        return await self._request_json(
            method='GET',
            path='/organizations',
            response_type=list[OrganizationReadSchema],
        )

    async def retrieve(self, *, id: str) -> OrganizationReadSchema:
        return await self._request_json(
            method='GET',
            path='/organizations/{organization_id}',
            path_params={'organization_id': id},
            response_type=OrganizationReadSchema,
        )

    async def update(self, *, id: str, data: OrganizationUpdateSchema | dict) -> OrganizationReadSchema:
        return await self._request_json(
            method='PATCH',
            path='/organizations/{organization_id}',
            path_params={'organization_id': id},
            data=data,
            response_type=OrganizationReadSchema,
        )

class AsyncProjectsResource(AsyncResourceBase):
    ai: AsyncProjectsAiResource
    cache: AsyncProjectsCacheResource
    dataframe: AsyncProjectsDataframeResource
    folders: AsyncProjectsFoldersResource
    json: AsyncProjectsJsonResource
    scheduler: AsyncProjectsSchedulerResource
    tasks: AsyncProjectsTasksResource
    variables: AsyncProjectsVariablesResource

    async def batch(self, *, data: ProjectsDeleteSchema | dict) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/projects/batch',
            data=data,
            response_type=CommonResponse,
        )

    async def copy(self, *, project_id: str, data: ProjectUpdateSchema | dict) -> ProjectReadSchema:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/copy',
            path_params={'project_id': project_id},
            data=data,
            response_type=ProjectReadSchema,
        )

    async def create(self, *, data: ProjectCreateSchema | dict) -> ProjectReadSchema:
        return await self._request_json(
            method='POST',
            path='/projects',
            data=data,
            response_type=ProjectReadSchema,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/projects/{project_id}',
            path_params={'project_id': id},
            response_type=CommonResponse,
        )

    async def graph(self, *, project_id: str) -> list[Any]:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/graph',
            path_params={'project_id': project_id},
            response_type=list[Any],
        )

    async def graph_ops(self, *, project_id: str, data: GraphOperationsAggregated | dict) -> GraphOperationResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/graph-ops',
            path_params={'project_id': project_id},
            data=data,
            response_type=GraphOperationResponse,
        )

    async def items(self, *, folder_id: str | None = None, organization_id: str | None = None, limit: int | None = 50, offset: int | None = 0, sort_by: Literal['default', 'updated_at'] | None = 'default', sort_order: Literal['asc', 'desc'] | None = 'desc', include_last_runs: bool | None = True) -> ProjectItemsPageSchema:
        return await self._request_json(
            method='GET',
            path='/projects/items',
            query={'folder_id': folder_id, 'organization_id': organization_id, 'limit': limit, 'offset': offset, 'sort_by': sort_by, 'sort_order': sort_order, 'include_last_runs': include_last_runs},
            response_type=ProjectItemsPageSchema,
        )

    async def list(self, *, sort_by: Literal['default', 'updated_at'] | None = 'default', sort_order: Literal['asc', 'desc'] | None = 'desc') -> list[ProjectReadSchema]:
        return await self._request_json(
            method='GET',
            path='/projects',
            query={'sort_by': sort_by, 'sort_order': sort_order},
            response_type=list[ProjectReadSchema],
        )

    async def logs(self, *, project_id: str, task_id: str, limit: int | None = 100, offset: int | None = 0) -> LogEntriesPageSchema:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/logs',
            path_params={'project_id': project_id},
            query={'task_id': task_id, 'limit': limit, 'offset': offset},
            response_type=LogEntriesPageSchema,
        )

    async def retrieve(self, *, id: str) -> ProjectReadSchema:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}',
            path_params={'project_id': id},
            response_type=ProjectReadSchema,
        )

    async def search(self, *, name: str, item_type: Literal['all', 'folder', 'project'] | None = 'all', folder_id: str | None = None, organization_id: str | None = None, limit: int | None = 50, offset: int | None = 0, sort_by: Literal['default', 'updated_at'] | None = 'default', sort_order: Literal['asc', 'desc'] | None = 'desc', include_last_runs: bool | None = True) -> ProjectSearchPageSchema:
        return await self._request_json(
            method='GET',
            path='/projects/search',
            query={'name': name, 'item_type': item_type, 'folder_id': folder_id, 'organization_id': organization_id, 'limit': limit, 'offset': offset, 'sort_by': sort_by, 'sort_order': sort_order, 'include_last_runs': include_last_runs},
            response_type=ProjectSearchPageSchema,
        )

    async def update(self, *, id: str, data: ProjectUpdateSchema | dict) -> ProjectReadSchema:
        return await self._request_json(
            method='PATCH',
            path='/projects/{project_id}',
            path_params={'project_id': id},
            data=data,
            response_type=ProjectReadSchema,
        )

class AsyncPublicResource(AsyncResourceBase):
    admin: AsyncPublicAdminResource
    db_connections: AsyncPublicDbConnectionsResource
    organizations: AsyncPublicOrganizationsResource
    projects: AsyncPublicProjectsResource

class AsyncPytestMonResource(AsyncResourceBase):
    async def fixtures(self) -> PytestEntityListResponse:
        return await self._request_json(
            method='GET',
            path='/pytest-mon/fixtures',
            response_type=PytestEntityListResponse,
        )

    async def tests(self) -> PytestEntityListResponse:
        return await self._request_json(
            method='GET',
            path='/pytest-mon/tests',
            response_type=PytestEntityListResponse,
        )

class AsyncQueueResource(AsyncResourceBase):
    async def execute(self, *, data: QueueActionRequest | dict) -> QueueActionResponse:
        return await self._request_json(
            method='POST',
            path='/queue',
            data=data,
            response_type=QueueActionResponse,
        )

    async def list(self, *, project_id: str | None = None, status_filter: list[TaskStatus] | None = None) -> QueueStateResponse:
        return await self._request_json(
            method='GET',
            path='/queue',
            query={'project_id': project_id, 'status_filter': status_filter},
            response_type=QueueStateResponse,
        )

class AsyncQueueTopicsResource(AsyncResourceBase):
    async def create(self, *, data: QueueTopicCreateSchema | dict) -> QueueTopicReadSchema:
        return await self._request_json(
            method='POST',
            path='/queue-topics',
            data=data,
            response_type=QueueTopicReadSchema,
        )

    async def data(self, *, topic_id: str, data: QueueTopicDataSchema | dict) -> QueueTopicDataSuccessSchema:
        return await self._request_json(
            method='POST',
            path='/queue-topics/{topic_id}/data',
            path_params={'topic_id': topic_id},
            data=data,
            response_type=QueueTopicDataSuccessSchema,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/queue-topics/{topic_id}',
            path_params={'topic_id': id},
            response_type=CommonResponse,
        )

    async def list(self, *, name: str | None = None) -> list[QueueTopicReadSchema]:
        return await self._request_json(
            method='GET',
            path='/queue-topics',
            query={'name': name},
            response_type=list[QueueTopicReadSchema],
        )

    async def retrieve(self, *, id: str) -> QueueTopicReadSchema:
        return await self._request_json(
            method='GET',
            path='/queue-topics/{topic_id}',
            path_params={'topic_id': id},
            response_type=QueueTopicReadSchema,
        )

    async def update(self, *, id: str, data: QueueTopicUpdateSchema | dict) -> QueueTopicReadSchema:
        return await self._request_json(
            method='PATCH',
            path='/queue-topics/{topic_id}',
            path_params={'topic_id': id},
            data=data,
            response_type=QueueTopicReadSchema,
        )

class AsyncSetupResource(AsyncResourceBase):
    async def app_config(self, *, data: SetupStepSubmitRequest | dict) -> SetupStatus:
        return await self._request_json(
            method='POST',
            path='/setup/app_config',
            data=data,
            response_type=SetupStatus,
        )

    async def organization(self, *, data: SetupStepSubmitRequest | dict) -> SetupStatus:
        return await self._request_json(
            method='POST',
            path='/setup/organization',
            data=data,
            response_type=SetupStatus,
        )

    async def status(self) -> SetupStatus:
        return await self._request_json(
            method='GET',
            path='/setup/status',
            response_type=SetupStatus,
        )

    async def superadmin(self, *, data: SetupStepSubmitRequest | dict) -> SetupStatus:
        return await self._request_json(
            method='POST',
            path='/setup/superadmin',
            data=data,
            response_type=SetupStatus,
        )

class AsyncStorageResource(AsyncResourceBase):
    download: AsyncStorageDownloadResource
    files: AsyncStorageFilesResource
    folder: AsyncStorageFolderResource
    path: AsyncStoragePathResource
    upload: AsyncStorageUploadResource

    async def list(self, *, connection_id: str, path: str | None = '', max_items: int | None = 1000) -> UserFileTreeSchema:
        return await self._request_json(
            method='GET',
            path='/storage/list',
            query={'connection_id': connection_id, 'path': path, 'max_items': max_items},
            response_type=UserFileTreeSchema,
        )

class AsyncStoreResource(AsyncResourceBase):
    async def batch(self, *, ttl: int | None = None, data: list[BatchItem] | dict) -> dict[str, Any]:
        return await self._request_json(
            method='POST',
            path='/store/batch',
            query={'ttl': ttl},
            data=data,
            response_type=dict[str, Any],
        )

    async def delete(self, *, key: str | None = None, keys: list[str] | None = None, pattern: str | None = None) -> dict[str, Any]:
        return await self._request_json(
            method='DELETE',
            path='/store',
            query={'key': key, 'keys': keys, 'pattern': pattern},
            response_type=dict[str, Any],
        )

    async def list(self, *, pattern: str | None = '*', limit: int | None = 10, offset: int | None = 0) -> dict[str, str]:
        return await self._request_json(
            method='GET',
            path='/store',
            query={'pattern': pattern, 'limit': limit, 'offset': offset},
            response_type=dict[str, str],
        )

    async def set(self, *, key: str, extend_key: bool | None = False, ttl: int | None = None, value: str | bytes) -> dict[str, Any]:
        return await self._request_content(
            method='POST',
            path='/store',
            query={'key': key, 'extend_key': extend_key, 'ttl': ttl},
            content=value,
            response_type=dict[str, Any],
        )

class AsyncSystemResource(AsyncResourceBase):
    async def runtime_config(self) -> RuntimeConfig:
        return await self._request_json(
            method='GET',
            path='/system/runtime-config',
            response_type=RuntimeConfig,
        )

    async def services_stats(self) -> ServicesStatus:
        return await self._request_json(
            method='GET',
            path='/system/services-stats',
            response_type=ServicesStatus,
        )

    async def stats(self) -> SystemInfo:
        return await self._request_json(
            method='GET',
            path='/system/stats',
            response_type=SystemInfo,
        )

    async def version(self) -> VersionInfo:
        return await self._request_json(
            method='GET',
            path='/system/version',
            response_type=VersionInfo,
        )

class AsyncUserResource(AsyncResourceBase):
    async def info(self) -> UserReadSchema:
        return await self._request_json(
            method='GET',
            path='/user/info',
            response_type=UserReadSchema,
        )

class AsyncUtilsResource(AsyncResourceBase):
    csv: AsyncUtilsCsvResource
    ddl: AsyncUtilsDdlResource

    async def sql_code_metadata(self, *, data: BodySqlCodeMetadataUtilsSqlCodeMetadataPost | dict) -> SQLCodeMetadata:
        return await self._request_json(
            method='POST',
            path='/utils/sql-code-metadata',
            data=data,
            response_type=SQLCodeMetadata,
        )

class AsyncAdminUsersResource(AsyncResourceBase):
    async def create(self, *, data: AdminUserCreateSchema | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/admin/users',
            data=data,
            response_type=CommonResponse,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/admin/users/{user_id}',
            path_params={'user_id': id},
            response_type=CommonResponse,
        )

    async def list(self, *, page: int | None = 1, limit: int | None = 30, email_contains: str | None = None) -> list[AdminUserReadSchema]:
        return await self._request_json(
            method='GET',
            path='/admin/users',
            query={'page': page, 'limit': limit, 'email_contains': email_contains},
            response_type=list[AdminUserReadSchema],
        )

    async def retrieve(self, *, id: str) -> AdminUserReadSchema:
        return await self._request_json(
            method='GET',
            path='/admin/users/{user_id}',
            path_params={'user_id': id},
            response_type=AdminUserReadSchema,
        )

    async def update(self, *, data: AdminUserUpdateSchema | dict) -> CommonResponse:
        return await self._request_json(
            method='PATCH',
            path='/admin/users',
            data=data,
            response_type=CommonResponse,
        )

class AsyncAppSettingsFieldsResource(AsyncResourceBase):
    required: AsyncAppSettingsFieldsRequiredResource

class AsyncExtensionsFrontendResource(AsyncResourceBase):
    assets: AsyncExtensionsFrontendAssetsResource

    async def retrieve(self, *, extension_name: str) -> ExtensionFrontendReadSchema:
        return await self._request_json(
            method='GET',
            path='/extensions/{extension_name}/frontend',
            path_params={'extension_name': extension_name},
            response_type=ExtensionFrontendReadSchema,
        )

class AsyncExtensionsStateResource(AsyncResourceBase):
    async def retrieve(self, *, extension_name: str, key: str | None = 'default') -> ExtensionStateReadSchema:
        return await self._request_json(
            method='GET',
            path='/extensions/{extension_name}/state',
            path_params={'extension_name': extension_name},
            query={'key': key},
            response_type=ExtensionStateReadSchema,
        )

    async def update(self, *, extension_name: str, key: str | None = 'default', data: ExtensionStateUpdateSchema | dict) -> ExtensionStateReadSchema:
        return await self._request_json(
            method='PUT',
            path='/extensions/{extension_name}/state',
            path_params={'extension_name': extension_name},
            query={'key': key},
            data=data,
            response_type=ExtensionStateReadSchema,
        )

class AsyncProjectsAiResource(AsyncResourceBase):
    analyze: AsyncProjectsAiAnalyzeResource

class AsyncProjectsCacheResource(AsyncResourceBase):
    clear: AsyncProjectsCacheClearResource

class AsyncProjectsDataframeResource(AsyncResourceBase):
    async def download(self, *, project_id: str, node_id: str, output_name: str | None = 'output') -> BinaryPayload:
        return await self._request_binary(
            method='GET',
            path='/projects/{project_id}/dataframe/{node_id}/download',
            path_params={'project_id': project_id, 'node_id': node_id},
            query={'output_name': output_name},
        )

    async def retrieve(self, *, project_id: str, node_id: str, output_name: str | None = 'output', offset: int | None = 0, limit: int | None = 1000) -> DataFrameData:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/dataframe/{node_id}',
            path_params={'project_id': project_id, 'node_id': node_id},
            query={'output_name': output_name, 'offset': offset, 'limit': limit},
            response_type=DataFrameData,
        )

class AsyncProjectsFoldersResource(AsyncResourceBase):
    async def create(self, *, data: ProjectFolderCreateSchema | dict) -> ProjectFolderReadSchema:
        return await self._request_json(
            method='POST',
            path='/projects/folders',
            data=data,
            response_type=ProjectFolderReadSchema,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/projects/folders/{folder_id}',
            path_params={'folder_id': id},
            response_type=CommonResponse,
        )

    async def update(self, *, id: str, data: ProjectFolderUpdateSchema | dict) -> ProjectFolderReadSchema:
        return await self._request_json(
            method='PATCH',
            path='/projects/folders/{folder_id}',
            path_params={'folder_id': id},
            data=data,
            response_type=ProjectFolderReadSchema,
        )

class AsyncProjectsJsonResource(AsyncResourceBase):
    async def retrieve(self, *, project_id: str, node_id: str, output_name: str | None = 'output', offset: int | None = 0, limit: int | None = 1000) -> JSONData:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/json/{node_id}',
            path_params={'project_id': project_id, 'node_id': node_id},
            query={'output_name': output_name, 'offset': offset, 'limit': limit},
            response_type=JSONData,
        )

class AsyncProjectsSchedulerResource(AsyncResourceBase):
    schedule: AsyncProjectsSchedulerScheduleResource

    async def scheduled(self) -> list[ProjectScheduleResponse]:
        return await self._request_json(
            method='GET',
            path='/projects/scheduler/scheduled',
            response_type=list[ProjectScheduleResponse],
        )

    async def unschedule(self, *, project_id: str) -> ScheduleResponse:
        return await self._request_json(
            method='POST',
            path='/projects/scheduler/unschedule',
            query={'project_id': project_id},
            response_type=ScheduleResponse,
        )

class AsyncProjectsTasksResource(AsyncResourceBase):
    async def cancel(self, *, project_id: str, task_id: str) -> TaskResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/tasks/{task_id}/cancel',
            path_params={'project_id': project_id, 'task_id': task_id},
            response_type=TaskResponse,
        )

    async def info(self, *, project_id: str, task_id: str) -> TaskInfo:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/tasks/{task_id}/info',
            path_params={'project_id': project_id, 'task_id': task_id},
            response_type=TaskInfo,
        )

    async def new(self, *, project_id: str, mode: PipelineExecutionMode | None = 'full', force_exec: bool | None = False, target_nodes: list[str] | None = None) -> TaskResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/tasks/new',
            path_params={'project_id': project_id},
            query={'mode': mode, 'force_exec': force_exec, 'target_nodes': target_nodes},
            response_type=TaskResponse,
        )

class AsyncProjectsVariablesResource(AsyncResourceBase):
    bulk: AsyncProjectsVariablesBulkResource

    async def create(self, *, project_id: str, variable_key: str, data: ProjectVariableCreate | dict) -> ProjectVariableRead:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/variables/{variable_key}',
            path_params={'project_id': project_id, 'variable_key': variable_key},
            data=data,
            response_type=ProjectVariableRead,
        )

    async def delete(self, *, project_id: str, variable_key: str) -> dict[str, Any]:
        return await self._request_json(
            method='DELETE',
            path='/projects/{project_id}/variables/{variable_key}',
            path_params={'project_id': project_id, 'variable_key': variable_key},
            response_type=dict[str, Any],
        )

    async def list(self, *, project_id: str) -> list[ProjectVariableRead]:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/variables/',
            path_params={'project_id': project_id},
            response_type=list[ProjectVariableRead],
        )

    async def retrieve(self, *, project_id: str, variable_key: str) -> ProjectVariableRead:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/variables/{variable_key}',
            path_params={'project_id': project_id, 'variable_key': variable_key},
            response_type=ProjectVariableRead,
        )

    async def set(self, *, project_id: str, data: dict[str, ProjectVariableBase] | dict) -> list[ProjectVariableRead]:
        return await self._request_json(
            method='PUT',
            path='/projects/{project_id}/variables/',
            path_params={'project_id': project_id},
            data=data,
            response_type=list[ProjectVariableRead],
        )

    async def update(self, *, project_id: str, variable_key: str, data: ProjectVariableUpdate | dict) -> ProjectVariableRead:
        return await self._request_json(
            method='PUT',
            path='/projects/{project_id}/variables/{variable_key}',
            path_params={'project_id': project_id, 'variable_key': variable_key},
            data=data,
            response_type=ProjectVariableRead,
        )

class AsyncPublicAdminResource(AsyncResourceBase):
    users: AsyncPublicAdminUsersResource

class AsyncPublicDbConnectionsResource(AsyncResourceBase):
    async def check(self, *, data: ClickhouseSqlNativeDefaultDriverConnectionCreateRequest | ClickhouseSqlHttpConnectionCreateRequest | FtpFileNoDriverConnectionCreateRequest | KafkaQueueNoDriverConnectionCreateRequest | MongodbSqlNoDriverConnectionCreateRequest | MssqlSqlPyodbcDefaultDriverConnectionCreateRequest | MssqlSqlAioodbcConnectionCreateRequest | MysqlSqlPymysqlDefaultDriverConnectionCreateRequest | MysqlSqlAiomysqlConnectionCreateRequest | OracleSqlOracledbDefaultDriverConnectionCreateRequest | PostgresSqlPsycopgDefaultDriverConnectionCreateRequest | PostgresSqlPsycopg2ConnectionCreateRequest | PostgresSqlAsyncpgConnectionCreateRequest | S3FileNoDriverConnectionCreateRequest | SftpFileNoDriverConnectionCreateRequest | SmbprotocolFileNoDriverConnectionCreateRequest | dict) -> ConnectionCheckResult:
        return await self._request_json(
            method='POST',
            path='/public/db-connections/check',
            data=data,
            response_type=ConnectionCheckResult,
        )

    async def check_by_id(self, *, connection_id: str, data: ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest | ClickhouseSqlHttpConnectionUpdateRequest | FtpFileNoDriverConnectionUpdateRequest | KafkaQueueNoDriverConnectionUpdateRequest | MongodbSqlNoDriverConnectionUpdateRequest | MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest | MssqlSqlAioodbcConnectionUpdateRequest | MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest | MysqlSqlAiomysqlConnectionUpdateRequest | OracleSqlOracledbDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopg2ConnectionUpdateRequest | PostgresSqlAsyncpgConnectionUpdateRequest | S3FileNoDriverConnectionUpdateRequest | SftpFileNoDriverConnectionUpdateRequest | SmbprotocolFileNoDriverConnectionUpdateRequest | None | dict | None = None) -> ConnectionCheckResult:
        return await self._request_json(
            method='POST',
            path='/public/db-connections/{connection_id}/check',
            path_params={'connection_id': connection_id},
            data=data,
            response_type=ConnectionCheckResult,
        )

    async def create(self, *, data: ClickhouseSqlNativeDefaultDriverConnectionCreateRequest | ClickhouseSqlHttpConnectionCreateRequest | FtpFileNoDriverConnectionCreateRequest | KafkaQueueNoDriverConnectionCreateRequest | MongodbSqlNoDriverConnectionCreateRequest | MssqlSqlPyodbcDefaultDriverConnectionCreateRequest | MssqlSqlAioodbcConnectionCreateRequest | MysqlSqlPymysqlDefaultDriverConnectionCreateRequest | MysqlSqlAiomysqlConnectionCreateRequest | OracleSqlOracledbDefaultDriverConnectionCreateRequest | PostgresSqlPsycopgDefaultDriverConnectionCreateRequest | PostgresSqlPsycopg2ConnectionCreateRequest | PostgresSqlAsyncpgConnectionCreateRequest | S3FileNoDriverConnectionCreateRequest | SftpFileNoDriverConnectionCreateRequest | SmbprotocolFileNoDriverConnectionCreateRequest | dict) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse:
        return await self._request_json(
            method='POST',
            path='/public/db-connections',
            data=data,
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse,
        )

    async def delete(self, *, id: str) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='DELETE',
            path='/public/db-connections/{connection_id}',
            path_params={'connection_id': id},
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

    async def kinds(self) -> list[ConnectionKindInfoResponse]:
        return await self._request_json(
            method='GET',
            path='/public/db-connections/kinds',
            response_type=list[ConnectionKindInfoResponse],
        )

    async def list(self, *, kind: Literal['file', 'queue', 'sql'] | str | None = None, type: Literal['clickhouse', 'ftp', 'kafka', 'mongodb', 'mssql', 'mysql', 'oracle', 'postgres', 's3', 'sftp', 'smbprotocol'] | str | None = None, name: str | None = None, labels: str | None = None, metadata: str | None = None, extra: str | None = None) -> list[ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse]:
        return await self._request_json(
            method='GET',
            path='/public/db-connections',
            query={'kind': kind, 'type': type, 'name': name, 'labels': labels, 'metadata': metadata, 'extra': extra},
            response_type=list[ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse],
        )

    async def retrieve(self, *, id: str) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='GET',
            path='/public/db-connections/{connection_id}',
            path_params={'connection_id': id},
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

    async def types(self) -> list[ConnectionTypeInfoResponse]:
        return await self._request_json(
            method='GET',
            path='/public/db-connections/types',
            response_type=list[ConnectionTypeInfoResponse],
        )

    async def update(self, *, id: str, data: ClickhouseSqlNativeDefaultDriverConnectionUpdateRequest | ClickhouseSqlHttpConnectionUpdateRequest | FtpFileNoDriverConnectionUpdateRequest | KafkaQueueNoDriverConnectionUpdateRequest | MongodbSqlNoDriverConnectionUpdateRequest | MssqlSqlPyodbcDefaultDriverConnectionUpdateRequest | MssqlSqlAioodbcConnectionUpdateRequest | MysqlSqlPymysqlDefaultDriverConnectionUpdateRequest | MysqlSqlAiomysqlConnectionUpdateRequest | OracleSqlOracledbDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopgDefaultDriverConnectionUpdateRequest | PostgresSqlPsycopg2ConnectionUpdateRequest | PostgresSqlAsyncpgConnectionUpdateRequest | S3FileNoDriverConnectionUpdateRequest | SftpFileNoDriverConnectionUpdateRequest | SmbprotocolFileNoDriverConnectionUpdateRequest | dict) -> ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse:
        return await self._request_json(
            method='PATCH',
            path='/public/db-connections/{connection_id}',
            path_params={'connection_id': id},
            data=data,
            response_type=ClickhouseSqlNativeDefaultDriverConnectionReadResponse | ClickhouseSqlHttpConnectionReadResponse | FtpFileNoDriverConnectionReadResponse | KafkaQueueNoDriverConnectionReadResponse | MongodbSqlNoDriverConnectionReadResponse | MssqlSqlPyodbcDefaultDriverConnectionReadResponse | MssqlSqlAioodbcConnectionReadResponse | MysqlSqlPymysqlDefaultDriverConnectionReadResponse | MysqlSqlAiomysqlConnectionReadResponse | OracleSqlOracledbDefaultDriverConnectionReadResponse | PostgresSqlPsycopgDefaultDriverConnectionReadResponse | PostgresSqlPsycopg2ConnectionReadResponse | PostgresSqlAsyncpgConnectionReadResponse | S3FileNoDriverConnectionReadResponse | SftpFileNoDriverConnectionReadResponse | SmbprotocolFileNoDriverConnectionReadResponse | BrokenConnectionReadResponse,
        )

class AsyncPublicOrganizationsResource(AsyncResourceBase):
    async def create(self, *, data: OrganizationCreateSchema | dict) -> OrganizationReadSchema:
        return await self._request_json(
            method='POST',
            path='/public/organizations',
            data=data,
            response_type=OrganizationReadSchema,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/public/organizations/{organization_id}',
            path_params={'organization_id': id},
            response_type=CommonResponse,
        )

    async def list(self) -> list[OrganizationReadSchema]:
        return await self._request_json(
            method='GET',
            path='/public/organizations',
            response_type=list[OrganizationReadSchema],
        )

    async def retrieve(self, *, id: str) -> OrganizationReadSchema:
        return await self._request_json(
            method='GET',
            path='/public/organizations/{organization_id}',
            path_params={'organization_id': id},
            response_type=OrganizationReadSchema,
        )

    async def update(self, *, id: str, data: OrganizationUpdateSchema | dict) -> OrganizationReadSchema:
        return await self._request_json(
            method='PATCH',
            path='/public/organizations/{organization_id}',
            path_params={'organization_id': id},
            data=data,
            response_type=OrganizationReadSchema,
        )

class AsyncPublicProjectsResource(AsyncResourceBase):
    tasks: AsyncPublicProjectsTasksResource

class AsyncStorageDownloadResource(AsyncResourceBase):
    async def file(self, *, connection_id: str, filename: str, path: str) -> BinaryPayload:
        return await self._request_binary(
            method='GET',
            path='/storage/download/file',
            query={'connection_id': connection_id, 'filename': filename, 'path': path},
        )

    async def presign(self, *, connection_id: str, filename: str, path: str) -> str:
        return await self._request_json(
            method='GET',
            path='/storage/download/presign',
            query={'connection_id': connection_id, 'filename': filename, 'path': path},
            response_type=str,
        )

class AsyncStorageFilesResource(AsyncResourceBase):
    async def delete(self, *, connection_id: str, data: DeleteFilesIn | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/storage/files/delete',
            query={'connection_id': connection_id},
            data=data,
            response_type=CommonResponse,
        )

class AsyncStorageFolderResource(AsyncResourceBase):
    async def create(self, *, connection_id: str, data: BodyCreateFolderStorageFolderCreatePost | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/storage/folder/create',
            query={'connection_id': connection_id},
            data=data,
            response_type=CommonResponse,
        )

    async def delete(self, *, connection_id: str, data: DeleteFolderIn | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/storage/folder/delete',
            query={'connection_id': connection_id},
            data=data,
            response_type=CommonResponse,
        )

class AsyncStoragePathResource(AsyncResourceBase):
    async def move(self, *, connection_id: str, data: MovePathIn | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/storage/path/move',
            query={'connection_id': connection_id},
            data=data,
            response_type=CommonResponse,
        )

    async def rename(self, *, connection_id: str, data: RenamePathIn | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/storage/path/rename',
            query={'connection_id': connection_id},
            data=data,
            response_type=CommonResponse,
        )

class AsyncStorageUploadResource(AsyncResourceBase):
    async def file(self, *, connection_id: str, file: FileUpload, path: str = '') -> CommonResponse:
        file_name, file_content, file_content_type = open_file_upload(file)
        return await self._request_multipart(
            method='POST',
            path='/storage/upload/file',
            query={'connection_id': connection_id},
            form_data={'path': path},
            files={'file': (file_name, file_content, file_content_type)},
            response_type=CommonResponse,
        )

    async def presign(self, *, connection_id: str, path: str, content_type_prefix: str, filename: str | None = None) -> PresignedPostOut:
        return await self._request_json(
            method='GET',
            path='/storage/upload/presign',
            query={'connection_id': connection_id, 'path': path, 'content_type_prefix': content_type_prefix, 'filename': filename},
            response_type=PresignedPostOut,
        )

class AsyncUtilsCsvResource(AsyncResourceBase):
    async def get_columns(self, *, data: BodyGetColumnsUtilsCsvGetColumnsPost | dict) -> list[str]:
        return await self._request_json(
            method='POST',
            path='/utils/csv/get-columns',
            data=data,
            response_type=list[str],
        )

class AsyncUtilsDdlResource(AsyncResourceBase):
    async def create_database(self, *, data: CreateDatabaseRequest | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/utils/ddl/create-database',
            data=data,
            response_type=CommonResponse,
        )

    async def create_schema(self, *, data: CreateSchemaRequest | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/utils/ddl/create-schema',
            data=data,
            response_type=CommonResponse,
        )

    async def create_table(self, *, data: CreateTableFromSchemaRequest | CreateTableFromSQLRequest | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/utils/ddl/create-table',
            data=data,
            response_type=CommonResponse,
        )

    async def generate_schema_ddl(self, *, data: GenerateSchemaDDLRequest | dict) -> GenerateSchemaDDLResponse:
        return await self._request_json(
            method='POST',
            path='/utils/ddl/generate-schema-ddl',
            data=data,
            response_type=GenerateSchemaDDLResponse,
        )

    async def generate_table_ddl(self, *, data: GenerateTableDDL | dict) -> GenerateTableDDLResponse:
        return await self._request_json(
            method='POST',
            path='/utils/ddl/generate-table-ddl',
            data=data,
            response_type=GenerateTableDDLResponse,
        )

class AsyncAppSettingsFieldsRequiredResource(AsyncResourceBase):
    async def list(self) -> list[str]:
        return await self._request_json(
            method='GET',
            path='/app-settings/fields/required',
            response_type=list[str],
        )

    async def unfilled(self, *, validate: bool | None = False) -> list[str]:
        return await self._request_json(
            method='GET',
            path='/app-settings/fields/required/unfilled',
            query={'validate': validate},
            response_type=list[str],
        )

class AsyncExtensionsFrontendAssetsResource(AsyncResourceBase):
    async def retrieve(self, *, extension_name: str, asset_path: str) -> BinaryPayload:
        return await self._request_binary(
            method='GET',
            path='/extensions/{extension_name}/frontend/assets/{asset_path}',
            path_params={'extension_name': extension_name, 'asset_path': asset_path},
        )

class AsyncProjectsAiAnalyzeResource(AsyncResourceBase):
    async def create(self, *, project_id: str, accept_language: str | None = None, data: AIAnalysisCreateSchema | dict) -> AIAnalysisCreateResponseSchema:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/ai/analyze',
            path_params={'project_id': project_id},
            headers={'Accept-Language': accept_language},
            data=data,
            response_type=AIAnalysisCreateResponseSchema,
        )

    async def list(self, *, project_id: str, limit: int | None = 20, offset: int | None = 0, status: AIAnalysisStatus | None = None, task_id: str | None = None) -> AIAnalysisHistoryResponseSchema:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/ai/analyze',
            path_params={'project_id': project_id},
            query={'limit': limit, 'offset': offset, 'status': status, 'task_id': task_id},
            response_type=AIAnalysisHistoryResponseSchema,
        )

    async def retrieve(self, *, request_id: str, project_id: str) -> AIAnalysisReadSchema:
        return await self._request_json(
            method='GET',
            path='/projects/{project_id}/ai/analyze/{request_id}',
            path_params={'request_id': request_id, 'project_id': project_id},
            response_type=AIAnalysisReadSchema,
        )

class AsyncProjectsCacheClearResource(AsyncResourceBase):
    async def data(self, *, project_id: str, data: ClearProjectDataCacheRequest | dict) -> ClearProjectDataCacheResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/cache/clear/data',
            path_params={'project_id': project_id},
            data=data,
            response_type=ClearProjectDataCacheResponse,
        )

    async def execute(self, *, project_id: str, data: ClearProjectCacheRequest | dict) -> ClearProjectCacheResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/cache/clear',
            path_params={'project_id': project_id},
            data=data,
            response_type=ClearProjectCacheResponse,
        )

    async def metadata(self, *, project_id: str, data: ClearProjectMetadataCacheRequest | dict) -> ClearProjectMetadataCacheResponse:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/cache/clear/metadata',
            path_params={'project_id': project_id},
            data=data,
            response_type=ClearProjectMetadataCacheResponse,
        )

class AsyncProjectsSchedulerScheduleResource(AsyncResourceBase):
    async def create(self, *, data: ProjectScheduleRequest | dict) -> ScheduleResponse:
        return await self._request_json(
            method='POST',
            path='/projects/scheduler/schedule',
            data=data,
            response_type=ScheduleResponse,
        )

    async def delete(self, *, id: str) -> ScheduleResponse:
        return await self._request_json(
            method='DELETE',
            path='/projects/scheduler/schedule/{project_id}',
            path_params={'project_id': id},
            response_type=ScheduleResponse,
        )

    async def update(self, *, id: str, data: ProjectSchedulePatchRequest | dict) -> ScheduleResponse:
        return await self._request_json(
            method='PATCH',
            path='/projects/scheduler/schedule/{project_id}',
            path_params={'project_id': id},
            data=data,
            response_type=ScheduleResponse,
        )

class AsyncProjectsVariablesBulkResource(AsyncResourceBase):
    async def update(self, *, id: str, data: ProjectVariablesBulkUpdate | dict) -> list[ProjectVariableRead]:
        return await self._request_json(
            method='POST',
            path='/projects/{project_id}/variables/bulk/update',
            path_params={'project_id': id},
            data=data,
            response_type=list[ProjectVariableRead],
        )

class AsyncPublicAdminUsersResource(AsyncResourceBase):
    async def create(self, *, data: AdminUserCreateSchema | dict) -> CommonResponse:
        return await self._request_json(
            method='POST',
            path='/public/admin/users',
            data=data,
            response_type=CommonResponse,
        )

    async def delete(self, *, id: str) -> CommonResponse:
        return await self._request_json(
            method='DELETE',
            path='/public/admin/users/{user_id}',
            path_params={'user_id': id},
            response_type=CommonResponse,
        )

    async def list(self, *, page: int | None = 1, limit: int | None = 30, email_contains: str | None = None) -> list[AdminUserReadSchema]:
        return await self._request_json(
            method='GET',
            path='/public/admin/users',
            query={'page': page, 'limit': limit, 'email_contains': email_contains},
            response_type=list[AdminUserReadSchema],
        )

    async def retrieve(self, *, id: str) -> AdminUserReadSchema:
        return await self._request_json(
            method='GET',
            path='/public/admin/users/{user_id}',
            path_params={'user_id': id},
            response_type=AdminUserReadSchema,
        )

    async def update(self, *, data: AdminUserUpdateSchema | dict) -> CommonResponse:
        return await self._request_json(
            method='PATCH',
            path='/public/admin/users',
            data=data,
            response_type=CommonResponse,
        )

class AsyncPublicProjectsTasksResource(AsyncResourceBase):
    async def cancel(self, *, project_id: str, task_id: str) -> TaskResponse:
        return await self._request_json(
            method='POST',
            path='/public/projects/{project_id}/tasks/{task_id}/cancel',
            path_params={'project_id': project_id, 'task_id': task_id},
            response_type=TaskResponse,
        )

    async def info(self, *, project_id: str, task_id: str) -> TaskInfo:
        return await self._request_json(
            method='GET',
            path='/public/projects/{project_id}/tasks/{task_id}/info',
            path_params={'project_id': project_id, 'task_id': task_id},
            response_type=TaskInfo,
        )

    async def new(self, *, project_id: str, mode: PipelineExecutionMode | None = 'full', force_exec: bool | None = False, target_nodes: list[str] | None = None) -> TaskResponse:
        return await self._request_json(
            method='POST',
            path='/public/projects/{project_id}/tasks/new',
            path_params={'project_id': project_id},
            query={'mode': mode, 'force_exec': force_exec, 'target_nodes': target_nodes},
            response_type=TaskResponse,
        )

def attach_async_resources(client) -> None:
    client.admin = AsyncAdminResource(client._transport)
    client.app_settings = AsyncAppSettingsResource(client._transport)
    client.config = AsyncConfigResource(client._transport)
    client.db_connections = AsyncDbConnectionsResource(client._transport)
    client.exceptions = AsyncExceptionsResource(client._transport)
    client.extensions = AsyncExtensionsResource(client._transport)
    client.logs = AsyncLogsResource(client._transport)
    client.metrics = AsyncMetricsResource(client._transport)
    client.nodes = AsyncNodesResource(client._transport)
    client.organizations = AsyncOrganizationsResource(client._transport)
    client.projects = AsyncProjectsResource(client._transport)
    client.public = AsyncPublicResource(client._transport)
    client.pytest_mon = AsyncPytestMonResource(client._transport)
    client.queue = AsyncQueueResource(client._transport)
    client.queue_topics = AsyncQueueTopicsResource(client._transport)
    client.setup = AsyncSetupResource(client._transport)
    client.storage = AsyncStorageResource(client._transport)
    client.store = AsyncStoreResource(client._transport)
    client.system = AsyncSystemResource(client._transport)
    client.user = AsyncUserResource(client._transport)
    client.utils = AsyncUtilsResource(client._transport)

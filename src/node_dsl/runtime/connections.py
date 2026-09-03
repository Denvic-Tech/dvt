from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

import fsspec
import sqlalchemy as sa
from db_connection.application.validation import ValidationService
from db_connection.connectors.ftp import FTPProperties, FTPSecrets, SFTPProperties
from db_connection.connectors.sql import SQLConnector
from db_connection.registry.defaults import S3Properties
from sqlalchemy import URL, Engine, create_engine

from core.db.connect.sqlalchemy_url import with_database
from core.types import FsCtx

from src.modules.db_connection.infra.connectors.dvt_service_files.schemas import (
    DVTServiceFilesProperties,
)
from src.modules.db_connection.infra.connectors.smbprotocol.schemas import (
    SMBProtocolProperties,
    SMBProtocolSecrets,
)
from src.modules.db_connection.validation_compat import normalize_connection_record_for_validation
from src.modules.file_storage.infra.fsspec_dvt_service_files import (
    register_dvt_service_files_filesystem,
)
from src.node_dsl.connection_types import FileConnectionRecord, SqlConnectionRecord
from src.node_dsl.runtime.integrations.file_connection.overrides import (
    ResolvedFileConnectionOverrides,
    ResolvedFTPConnectionOverrides,
    ResolvedS3ConnectionOverrides,
    ResolvedSFTPConnectionOverrides,
)


def clean_connection_path(*parts: str | None) -> str:
    return "/".join(part.strip("/") for part in parts if part and part.strip("/"))


def restore_file_url(ctx: FsCtx, path: str) -> str:
    if "://" in path:
        return path

    path = path.lstrip("/")
    if ctx.url_root:
        separator = "" if ctx.url_root.endswith("/") else "/"
        return f"{ctx.url_root}{separator}{path}"

    return f"{ctx.protocol}://{path}"


@lru_cache
def _build_validation_service() -> ValidationService:
    from src.modules.db_connection.facade import build_registry

    return ValidationService(build_registry())


def validate_connection_record(record: object):
    return _build_validation_service().validate(normalize_connection_record_for_validation(record))


def _looks_like_new_connection_record(value: object) -> bool:
    if isinstance(value, Mapping):
        return all(attr in value for attr in ("kind", "type", "properties"))
    return all(hasattr(value, attr) for attr in ("kind", "type", "properties"))


def _looks_like_legacy_connection(value: object) -> bool:
    return hasattr(value, "connection_properties") and hasattr(value, "type")


def _looks_like_legacy_s3_properties(value: object) -> bool:
    return all(
        hasattr(value, attr)
        for attr in ("bucket", "region_name", "endpoint_url", "access_token_id", "access_token_key")
    )


def _looks_like_legacy_ftp_properties(value: object) -> bool:
    return all(hasattr(value, attr) for attr in ("host", "port", "username"))


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _build_network_url_root(protocol: str, host: str, port: int | None) -> str:
    return f"{protocol}://{host}:{port}" if port is not None else f"{protocol}://{host}"


def _validated_props_and_secrets(connection: object) -> tuple[object, object | None]:
    if isinstance(connection, (SqlConnectionRecord, FileConnectionRecord)):
        validated = validate_connection_record(connection.record)
        return validated.properties, validated.secrets

    record = connection.record if hasattr(connection, "record") else None
    if record is not None:
        validated = validate_connection_record(record)
        return validated.properties, validated.secrets

    if _looks_like_new_connection_record(connection):
        validated = validate_connection_record(connection)
        return validated.properties, validated.secrets

    if _looks_like_legacy_connection(connection):
        return connection.connection_properties, None

    raise TypeError(f"Unsupported connection object: {type(connection)!r}")


def _resolve_sqlite_url(connection: SqlConnectionRecord) -> URL:
    props = dict(connection.properties or {})
    driver = connection.driver or "pysqlite"
    drivername = driver if str(driver).startswith("sqlite") else f"sqlite+{driver}"
    return URL.create(
        drivername=drivername,
        database=props.get("database") or ":memory:",
    )


def resolve_sql_connection_url(
    connection: SqlConnectionRecord | Engine,
    *,
    database_name: str | None = None,
) -> URL | str:
    if isinstance(connection, sa.Engine):
        return with_database(connection.url, database_name)

    if _looks_like_new_connection_record(connection):
        connection = SqlConnectionRecord(connection)

    if not isinstance(connection, SqlConnectionRecord):
        if hasattr(connection, "url"):
            return with_database(connection.url, database_name)
        raise TypeError(f"Unsupported SQL connection object: {type(connection)!r}")

    if connection.type == "sqlite":
        return with_database(_resolve_sqlite_url(connection), database_name)

    validated = validate_connection_record(connection.record)
    url = SQLConnector(preferred_mode="sync").build_connection_url(validated)
    if isinstance(url, sa.URL):
        return with_database(url, database_name)
    return url


def resolve_sql_engine(
    connection: SqlConnectionRecord | Engine,
    *,
    database_name: str | None = None,
) -> Engine:
    if isinstance(connection, sa.Engine) and not database_name:
        return connection
    if not isinstance(connection, SqlConnectionRecord) and hasattr(connection, "dialect"):
        if database_name:
            raise TypeError(
                f"Cannot override database for SQL connection object without URL: {type(connection)!r}"
            )
        return connection
    return create_engine(resolve_sql_connection_url(connection, database_name=database_name))


def resolve_sql_dialect_name(connection: SqlConnectionRecord | Engine) -> str | None:
    return resolve_sql_engine(connection).dialect.name


def resolve_file_fs_context(
    connection: FileConnectionRecord,
    *,
    path: str | None = None,
    root_only: bool = False,
    create_fs: bool = True,
    timeout_sec: int | None = None,
    ftp_block_size: int | None = None,
    overrides: ResolvedFileConnectionOverrides | None = None,
) -> FsCtx:
    props, secrets = _validated_props_and_secrets(connection)

    if isinstance(props, DVTServiceFilesProperties):
        register_dvt_service_files_filesystem()
        root_prefix = props.root_prefix.strip("/")
        root_path = "" if root_only else clean_connection_path(path or "")
        full_path = f"dvtfiles://{props.project_id}/{root_path}" if root_path else f"dvtfiles://{props.project_id}"
        storage_options = {
            "organization_id": props.organization_id,
            "project_id": props.project_id,
            "root_prefix": root_prefix,
        }
        fs = fsspec.filesystem("dvtfiles", **storage_options) if create_fs else None
        return FsCtx(
            fs=fs,
            protocol="dvtfiles",
            path=full_path,
            storage_options=storage_options,
            url_root=f"dvtfiles://{props.project_id}",
        )

    if isinstance(props, S3Properties) or _looks_like_legacy_s3_properties(props):
        bucket = getattr(props, "bucket", "")
        prefix = getattr(props, "prefix", "") or ""
        verify = getattr(props, "verify", True)
        if isinstance(overrides, ResolvedS3ConnectionOverrides):
            if overrides.bucket is not None:
                bucket = overrides.bucket
            if overrides.prefix is not None:
                prefix = overrides.prefix
            if overrides.verify is not None:
                verify = overrides.verify

        inner_path = "" if root_only else clean_connection_path(prefix, path or "")
        if root_only:
            full_path = f"s3://{bucket}/{prefix.strip('/')}" if prefix else f"s3://{bucket}"
        else:
            full_path = f"s3://{bucket}/{inner_path}" if inner_path else f"s3://{bucket}"

        storage_options: dict[str, Any] = {
            "key": _coalesce(
                None if secrets is None else getattr(secrets, "access_token_id", None),
                getattr(props, "access_token_id", None),
            ),
            "secret": _coalesce(
                None if secrets is None else getattr(secrets, "access_token_key", None),
                getattr(props, "access_token_key", None),
            ),
            "client_kwargs": {
                "endpoint_url": props.endpoint_url,
                "verify": verify,
            },
            "use_ssl": props.use_ssl,
        }
        config_kwargs: dict[str, Any] = {
            "response_checksum_validation": "when_required",
            "request_checksum_calculation": "when_required",
        }
        if props.path_style:
            config_kwargs["s3"] = {"addressing_style": "path"}
        if props.signature_version:
            config_kwargs["signature_version"] = props.signature_version
        if timeout_sec is not None:
            config_kwargs["connect_timeout"] = timeout_sec
            config_kwargs["read_timeout"] = timeout_sec
        storage_options["config_kwargs"] = config_kwargs
        session_token = _coalesce(
            None if secrets is None else getattr(secrets, "session_token", None),
            getattr(props, "session_token", None),
        )
        if session_token:
            storage_options["token"] = session_token

        fs = fsspec.filesystem("s3", **storage_options) if create_fs else None
        return FsCtx(
            fs=fs,
            protocol="s3",
            path=full_path,
            storage_options=storage_options,
            url_root="s3://",
        )

    if isinstance(props, SMBProtocolProperties):
        smb_secrets = SMBProtocolSecrets.model_validate(secrets)
        protocol = "smb"
        share = clean_connection_path(props.share)
        inner_path = "" if root_only else clean_connection_path(share, path or "")
        url_root = _build_network_url_root(protocol, props.host, props.port)
        full_path = (
            f"{url_root}/{share}"
            if root_only and share
            else url_root
            if root_only
            else f"{url_root}/{inner_path}"
        )
        storage_options = {
            "host": props.host,
            "port": props.port,
            "username": props.username,
            "password": smb_secrets.password,
        }
        if timeout_sec is not None:
            storage_options["timeout"] = timeout_sec
        fs = fsspec.filesystem(protocol, **storage_options) if create_fs else None
        return FsCtx(
            fs=fs,
            protocol=protocol,
            path=full_path,
            storage_options=storage_options,
            host=props.host,
            port=props.port,
            url_root=url_root,
        )

    if isinstance(props, SFTPProperties):
        initial_directory = props.initial_directory
        if isinstance(overrides, ResolvedSFTPConnectionOverrides) and overrides.initial_directory is not None:
            initial_directory = overrides.initial_directory

        inner_path = "" if root_only else clean_connection_path(initial_directory, path or "")
        root_path = clean_connection_path(initial_directory)
        url_root = _build_network_url_root("sftp", props.host, props.port)
        full_path = (
            f"{url_root}/{root_path}"
            if root_only and root_path
            else url_root
            if root_only
            else f"{url_root}/{inner_path}"
        )
        storage_options = {
            "host": props.host,
            "port": props.port,
            "username": props.username,
            "password": None if secrets is None else getattr(secrets, "password", None),
            "key_filename": props.private_key_path,
            "allow_agent": props.allow_agent,
        }
        fs = fsspec.filesystem(
            "sftp",
            **{key: value for key, value in storage_options.items() if value is not None},
        ) if create_fs else None
        return FsCtx(
            fs=fs,
            protocol="sftp",
            path=full_path,
            storage_options={key: value for key, value in storage_options.items() if value is not None},
            host=props.host,
            port=props.port,
            url_root=url_root,
        )

    if not isinstance(props, FTPProperties) and not _looks_like_legacy_ftp_properties(props):
        raise TypeError(f"Unsupported file connection properties type: {type(props)}")

    ftp_secrets = FTPSecrets() if secrets is None else secrets
    protocol = "ftp"
    initial_directory = getattr(props, "initial_directory", None)
    if isinstance(overrides, ResolvedFTPConnectionOverrides) and overrides.initial_directory is not None:
        initial_directory = overrides.initial_directory
    inner_path = "" if root_only else clean_connection_path(initial_directory, path or "")
    root_path = clean_connection_path(initial_directory)
    url_root = _build_network_url_root(protocol, props.host, props.port)
    full_path = (
        f"{url_root}/{root_path}"
        if root_only and root_path
        else url_root
        if root_only
        else f"{url_root}/{inner_path}"
    )
    storage_options = {
        "host": props.host,
        "port": props.port,
        "username": "anonymous" if getattr(props, "anonymous", False) else (props.username or ""),
        "password": (
            ""
            if getattr(props, "anonymous", False)
            else _coalesce(getattr(ftp_secrets, "password", None), getattr(props, "password", "")) or ""
        ),
    }
    if timeout_sec is not None:
        storage_options["timeout"] = timeout_sec
    if ftp_block_size is not None:
        storage_options["block_size"] = ftp_block_size
    fs = fsspec.filesystem(protocol, **storage_options) if create_fs else None
    return FsCtx(
        fs=fs,
        protocol=protocol,
        path=full_path,
        storage_options=storage_options,
        host=props.host,
        port=props.port,
        url_root=url_root,
    )

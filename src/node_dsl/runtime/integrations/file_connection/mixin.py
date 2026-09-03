from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.types import FsCtx

from src.node_dsl.connection_types import FileConnectionRecord
from src.node_dsl.core.input_values import resolve_node_input_value
from src.node_dsl.field import InputField
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_mixins.base import NodeFieldsMixin
from src.node_dsl.runtime.connections import resolve_file_fs_context

from .filesystem import FileConnectionRuntime
from .overrides import (
    FileConnectionOverridesInput,
    FTPConnectionOverrides,
    ResolvedFileConnectionOverrides,
    ResolvedFTPConnectionOverrides,
    ResolvedS3ConnectionOverrides,
    ResolvedSFTPConnectionOverrides,
    S3ConnectionOverrides,
    SFTPConnectionOverrides,
    parse_file_connection_overrides,
)


def _normalize_connection_type(value: object) -> str:
    return str(getattr(value, "value", value)).lower()


class FileConnectionInputMixin(NodeFieldsMixin):
    connection: FileConnectionRecord = InputField()
    connection_overrides: FileConnectionOverridesInput | None = InputField(default=None)

    def _runtime_variables(self) -> dict[str, Any]:
        runtime_variables: dict[str, Any] = {}
        project_variables = self.project_variables
        if project_variables is not None:
            runtime_variables.update(project_variables.raw_values)
        if isinstance(self.input_variables, dict):
            runtime_variables.update(self.input_variables)
        return runtime_variables

    def _resolve_override_string(self, value: object, field_name: str) -> str | None:
        try:
            resolved_value = resolve_node_input_value(
                value,
                variables=self._runtime_variables(),
                target_type="STRING",
                allow_expressions=True,
                expression_policy="default",
                allow_unresolved=False,
                allow_none=True,
            )
        except ValueError as err:
            raise ValueError(f"Failed to resolve connection_overrides.{field_name}: {err}") from err

        if resolved_value is None:
            return None
        if not isinstance(resolved_value, str):
            raise TypeError(
                f"Field 'connection_overrides.{field_name}' must resolve to string or null."
            )
        return resolved_value

    def _resolve_override_boolean(self, value: object, field_name: str) -> bool | None:
        try:
            resolved_value = resolve_node_input_value(
                value,
                variables=self._runtime_variables(),
                target_type="BOOLEAN",
                allow_expressions=True,
                expression_policy="default",
                allow_unresolved=False,
                allow_none=True,
            )
        except ValueError as err:
            raise ValueError(f"Failed to resolve connection_overrides.{field_name}: {err}") from err

        if resolved_value is None:
            return None
        if not isinstance(resolved_value, bool):
            raise TypeError(
                f"Field 'connection_overrides.{field_name}' must resolve to boolean or null."
            )
        return resolved_value

    def _resolve_connection_overrides(self) -> ResolvedFileConnectionOverrides | None:
        if self.connection_overrides is None:
            return None

        connection_type = _normalize_connection_type(self.connection.type)
        if connection_type == "smbprotocol":
            raise ValueError("SMB connections do not support connection_overrides.")

        try:
            parsed = parse_file_connection_overrides(self.connection_overrides)
        except ValidationError as err:
            raise ValueError(f"Invalid connection_overrides payload: {err}") from err

        if parsed.type != connection_type:
            raise ValueError(
                "connection_overrides.type does not match connection.type: "
                f"got '{parsed.type}', expected '{connection_type}'."
            )

        if isinstance(parsed, S3ConnectionOverrides):
            return ResolvedS3ConnectionOverrides(
                bucket=self._resolve_override_string(parsed.bucket, "bucket"),
                prefix=self._resolve_override_string(parsed.prefix, "prefix"),
                verify=self._resolve_override_boolean(parsed.verify, "verify"),
            )

        if isinstance(parsed, FTPConnectionOverrides):
            return ResolvedFTPConnectionOverrides(
                initial_directory=self._resolve_override_string(
                    parsed.initial_directory,
                    "initial_directory",
                ),
            )

        if isinstance(parsed, SFTPConnectionOverrides):
            return ResolvedSFTPConnectionOverrides(
                initial_directory=self._resolve_override_string(
                    parsed.initial_directory,
                    "initial_directory",
                ),
            )

        raise ValueError(f"Unsupported connection_overrides type: {type(parsed)!r}")

    @on_validation
    def validate_connection_overrides(self) -> None:
        self._resolve_connection_overrides()

    def build_file_fs_context(
        self,
        *,
        path: str | None = None,
        root_only: bool = False,
        create_fs: bool = True,
        timeout_sec: int | None = None,
        ftp_block_size: int | None = None,
    ) -> FsCtx:
        return resolve_file_fs_context(
            self.connection,
            path=path,
            root_only=root_only,
            create_fs=create_fs,
            timeout_sec=timeout_sec,
            ftp_block_size=ftp_block_size,
            overrides=self._resolve_connection_overrides(),
        )

    def build_file_runtime(
        self,
        *,
        path: str | None = None,
        root_only: bool = False,
        timeout_sec: int | None = None,
        ftp_block_size: int | None = None,
    ) -> FileConnectionRuntime:
        return FileConnectionRuntime(
            self.build_file_fs_context(
                path=path,
                root_only=root_only,
                create_fs=False,
                timeout_sec=timeout_sec,
                ftp_block_size=ftp_block_size,
            )
        )

    def _get_file_runtime(
        self,
        *,
        path: str | None = None,
        root_only: bool = False,
        timeout_sec: int | None = None,
        ftp_block_size: int | None = None,
    ) -> FileConnectionRuntime:
        return FileConnectionRuntime(
            self._get_fs_context(
                path=path,
                root_only=root_only,
                create_fs=False,
                timeout_sec=timeout_sec,
                ftp_block_size=ftp_block_size,
            )
        )

    def _get_fs_context(
        self,
        *,
        path: str | None = None,
        root_only: bool = False,
        create_fs: bool = True,
        timeout_sec: int | None = None,
        ftp_block_size: int | None = None,
    ) -> FsCtx:
        return self.build_file_fs_context(
            path=path,
            root_only=root_only,
            create_fs=create_fs,
            timeout_sec=timeout_sec,
            ftp_block_size=ftp_block_size,
        )

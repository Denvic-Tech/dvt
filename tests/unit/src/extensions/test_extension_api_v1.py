from dvt_extension_api.v1.database import ExtensionAsyncSessionDep
from dvt_extension_api.v1.execution import ExecMode, ExecutionMode
from dvt_extension_api.v1.gateway import (
    CurrentAdminDep,
    CurrentSuperadminDep,
    CurrentUserDep,
)
from dvt_extension_api.v1.logging import get_logger
from dvt_extension_api.v1.metadata import Column, DataFrameMetadata, DataType, get_df_metadata
from dvt_extension_api.v1.node import (
    BaseNode,
    DFOutputBaseNode,
    FileConnectionInputMixin,
    IO,
    InputField,
    OutputField,
    S3ConnectionRecord,
    on_validation,
)
from dvt_extension_api.v1.state import get_extension_state, set_extension_state
from dvt_extension_api.v1.storage import FsCtx, S3Client, resolve_file_connection_context


def test_representative_extension_api_v1_imports() -> None:
    symbols = (
        BaseNode,
        DFOutputBaseNode,
        FileConnectionInputMixin,
        IO,
        InputField,
        OutputField,
        S3ConnectionRecord,
        on_validation,
        Column,
        DataFrameMetadata,
        DataType,
        get_df_metadata,
        ExecMode,
        ExecutionMode,
        CurrentUserDep,
        CurrentAdminDep,
        CurrentSuperadminDep,
        ExtensionAsyncSessionDep,
        get_logger,
        get_extension_state,
        set_extension_state,
        FsCtx,
        S3Client,
        resolve_file_connection_context,
    )

    assert all(symbol is not None for symbol in symbols)

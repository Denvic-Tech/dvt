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
    IO,
    BaseNode,
    DFOutputBaseNode,
    FileConnectionInputMixin,
    InputField,
    OutputField,
    S3ConnectionRecord,
    on_validation,
)
from dvt_extension_api.v1.parquet import (
    DEFAULT_ADVANCED_TEMPLATE,
    FilenameTemplate,
    NamingContext,
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
        DEFAULT_ADVANCED_TEMPLATE,
        FilenameTemplate,
        NamingContext,
    )

    assert all(symbol is not None for symbol in symbols)


def test_parquet_filename_template_facade() -> None:
    template = FilenameTemplate("batch-<increment>-<uuid>")

    rendered = template.render(NamingContext(partition_index=0, increment=7))

    assert template.template == "batch-<increment>-<uuid>.parquet"
    assert template.extract_increment(rendered) == 7
    assert template.matches(rendered)
    assert rendered.startswith("batch-00007-")
    assert rendered.endswith(".parquet")


def test_parquet_filename_template_rejects_unsafe_path() -> None:
    try:
        FilenameTemplate("nested/<increment>.parquet")
    except ValueError as error:
        assert "directory separators" in str(error)
    else:
        raise AssertionError("Unsafe filename template was accepted")


def test_parquet_filename_template_rejects_dot_names() -> None:
    for value in (".", ".."):
        try:
            FilenameTemplate(value)
        except ValueError as error:
            assert "cannot be '.' or '..'" in str(error)
        else:
            raise AssertionError(f"Unsafe filename template {value!r} was accepted")

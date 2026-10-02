from core.types import DataFrameMetadata

from src.clients.gateway_sdk.generated.models import DataFrameMetadataInput
from src.modules.kafka_consumption.infra.dataframe import (
    kafka_dataframe_metadata,
    messages_to_dataframe,
)
from src.node_dsl.base_node.df_output import DFOutputBaseNode


def test_sdk_preserves_nested_arrow_metadata():
    metadata = kafka_dataframe_metadata()
    sdk = DataFrameMetadataInput.model_validate_json(metadata.model_dump_json(by_alias=True))
    headers = next(column for column in sdk.columns if column.name == "headers")
    assert headers.dtype == "LIST"
    assert headers.dtype_metadata.arrow_type.fields[0].type.kind == "struct"
    restored = DataFrameMetadata.model_validate_json(sdk.model_dump_json(by_alias=True))
    assert (
        DFOutputBaseNode.build_empty_pdf_from_metadata(restored).dtypes.to_dict()
        == messages_to_dataframe(()).dtypes.to_dict()
    )

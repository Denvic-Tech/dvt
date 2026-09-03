from core.types import DBDialect, Metadata

from src.exception_registry.schema import RegisteredExceptionSchema
from src.modules.db_connection.facade import build_api_schema_set
from src.modules.pipeline_graph.infra.schemas import GraphEdgeUISchema, GraphNodeUISchema
from src.node_dsl.core.input_values import NodeInputValue, NodeInputValues
from src.node_dsl.types import NodeMetadata, NodeOutputMetadata
from src.node_dsl.variables.types import VariableDescriptorMetadata, VariableMapMetadata
from src.pipeline.types import PipelineMetadata
from src.schemas.event import Event, EventType
from src.schemas.node_definition import (
    BaseVariableDefinitionModel,
    InputDefinitionKey,
    InputDefinitionModel,
    LiteralInputDefinitionKey,
    LiteralOutputDefinitionKey,
    NodeDefinition,
    OutputDefinitionKey,
    OutputDefinitionModel,
)

db_connections_api_schema_set = build_api_schema_set()

included_models = [
    ("Event", Event),
    ("DBDialect", DBDialect),
    ("Metadata", Metadata),
    ("NodeOutputMetadata", NodeOutputMetadata),
    ("NodeMetadata", NodeMetadata),
    ("PipelineMetadata", PipelineMetadata),
    ("VariableDescriptorMetadata", VariableDescriptorMetadata),
    ("VariableMapMetadata", VariableMapMetadata),
    ("EventType", EventType),
    ("RegisteredException", RegisteredExceptionSchema),

    ("NodeDefinition", NodeDefinition),
    ("BaseVariableDefinitionModel", BaseVariableDefinitionModel),
    ("InputDefinitionModel", InputDefinitionModel),
    ("OutputDefinitionModel", OutputDefinitionModel),
    ("LiteralInputDefinitionKey", LiteralInputDefinitionKey),
    ("LiteralOutputDefinitionKey", LiteralOutputDefinitionKey),
    ("InputDefinitionKey", InputDefinitionKey),
    ("OutputDefinitionKey", OutputDefinitionKey),

    ("NodeInputValue", NodeInputValue),
    ("NodeInputValues", NodeInputValues),

    ("GraphNodeUISchema", GraphNodeUISchema),
    ("GraphEdgeUISchema", GraphEdgeUISchema),

    ("DBConnectionCreateV1", db_connections_api_schema_set.create),
    ("DBConnectionReadV1", db_connections_api_schema_set.read),
    ("DBConnectionUpdateV1", db_connections_api_schema_set.update),
    ("ConnectionKindV1", db_connections_api_schema_set.connection_kind),
    ("ConnectionTypeV1", db_connections_api_schema_set.connection_type)
]

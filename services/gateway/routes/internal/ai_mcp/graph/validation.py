"""Node and edge checks followed by whole-pipeline validation."""

from dataclasses import dataclass

from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.node_dsl.core.input_values import parse_node_input_value
from src.pipeline.graph import build_pipeline_from_graph
from src.pipeline.validation import validate_pipeline
from src.schemas.node_definition import InputDefinitionModel, NodeDefinition

from ..auth import MCPPrincipal
from .connection_validation import ServiceReferences, validate_node_connections
from .connections import connection_input_names, connection_object_input_names
from .diagnostics import Diagnostic, Diagnostics
from .input_validation import expression_validation_error, graph_constant_validation_error
from .mappers import edge_to_ui, node_to_ui
from .node_policies import generic_code_errors, graph_warnings, read_table_configuration_errors
from .state import GraphChanges, GraphState, NodeState


@dataclass(frozen=True)
class InputContext:
    incoming: set[tuple[str, str]]
    project_variables: set[str]
    connection_inputs: set[str]
    object_inputs: set[str]


def _validate_input(
    node: NodeState,
    name: str,
    definition: InputDefinitionModel,
    context: InputContext,
) -> list[Diagnostic]:
    location = {"node_id": node.id, "input": name}
    errors = []
    if (
        not definition.optional
        and definition.default is None
        and name not in node.inputs
        and (node.id, name) not in context.incoming
        and name not in context.object_inputs
    ):
        errors.append({"code": "REQUIRED_INPUT_MISSING", **location})
    parsed = parse_node_input_value(node.inputs.get(name))
    if parsed is None:
        return errors
    if parsed.dvt_type == "expr":
        if not definition.allow_expressions:
            errors.append({"code": "EXPRESSION_NOT_ALLOWED", **location})
        else:
            message = expression_validation_error(
                definition,
                expression=parsed.value,
                expression_kind=parsed.expression_kind,
                project_variable_names=context.project_variables,
            )
            if message:
                errors.append({"code": "INVALID_EXPRESSION", **location, "message": message})
    elif parsed.dvt_type == "const":
        message = graph_constant_validation_error(
            definition,
            parsed.value,
            node_id=node.id,
            input_name=name,
            incoming_inputs=context.incoming,
            connection_input_names=context.connection_inputs,
        )
        if message:
            errors.append({"code": "INVALID_CONSTANT", **location, "message": message})
    return errors


def node_input_errors(
    node: NodeState,
    definition: NodeDefinition,
    *,
    incoming: set[tuple[str, str]],
    project_variables: set[str],
) -> list[Diagnostic]:
    context = InputContext(
        incoming,
        project_variables,
        connection_input_names(node.node_type),
        connection_object_input_names(node.node_type),
    )
    errors = []
    unknown = sorted(set(node.inputs) - definition.input_definitions.keys())
    if unknown:
        errors.append({"code": "UNKNOWN_INPUT", "node_id": node.id, "inputs": unknown})
    for name, input_definition in definition.input_definitions.items():
        errors.extend(_validate_input(node, name, input_definition, context))
    return errors


def edge_port_errors(graph: GraphState, definitions: dict[str, NodeDefinition]) -> list[Diagnostic]:
    """Check each endpoint independently; unavailable node types are reported by node checks."""
    errors = []
    for edge in graph.edges.values():
        source = definitions.get(graph.nodes[edge.source].node_type)
        target = definitions.get(graph.nodes[edge.target].node_type)
        if source is not None and edge.source_output not in source.output_definitions:
            errors.append(
                {
                    "code": "UNKNOWN_SOURCE_OUTPUT",
                    "node_id": edge.source,
                    "connection_id": edge.id,
                    "endpoint": "source",
                    "port": edge.source_output,
                }
            )
        if target is not None and edge.target_input not in target.input_definitions:
            errors.append(
                {
                    "code": "UNKNOWN_TARGET_INPUT",
                    "node_id": edge.target,
                    "connection_id": edge.id,
                    "endpoint": "target",
                    "port": edge.target_input,
                }
            )
    return errors


def pipeline_errors(graph: GraphState, project: ProjectRecord) -> list[Diagnostic]:
    owner = {
        "project_id": project.id,
        "user_id": project.user_id,
        "organization_id": project.organization_id,
    }
    nodes = [
        graph_nodes_dto.to_persistent(node_to_ui(node), **owner) for node in graph.nodes.values()
    ]
    edges = [
        graph_edges_dto.to_persistent(edge_to_ui(edge), **owner) for edge in graph.edges.values()
    ]
    if not nodes:
        return [{"code": "PIPELINE_EMPTY"}]
    validation = validate_pipeline(build_pipeline_from_graph(nodes, edges))
    if not validation.is_valid:
        return [{"code": "PIPELINE_INVALID", "validation": validation.model_dump(mode="json")}]
    return []


async def validate_prepared_graph(
    graph: GraphState,
    changes: GraphChanges,
    *,
    definitions: dict[str, NodeDefinition],
    project: ProjectRecord,
    principal: MCPPrincipal,
    existing_references: ServiceReferences,
) -> Diagnostics:
    diagnostics = Diagnostics()
    incoming = {(edge.target, edge.target_input) for edge in graph.edges.values()}
    project_variables = set((project.variables or {}).keys())
    for node in graph.nodes.values():
        definition = definitions.get(node.node_type)
        if definition is None:
            diagnostics.errors.append(
                {
                    "code": "NODE_NOT_AVAILABLE",
                    "node_id": node.id,
                    "node_type": node.node_type,
                }
            )
            continue
        diagnostics.errors.extend(
            node_input_errors(
                node,
                definition,
                incoming=incoming,
                project_variables=project_variables,
            )
        )
        diagnostics.errors.extend(
            await validate_node_connections(
                node,
                definition,
                principal=principal,
                project_id=project.id,
                incoming_inputs=incoming,
                existing_references=existing_references,
            )
        )
        if node.node_type == "ReadTableFromDBV3":
            diagnostics.errors.extend(
                read_table_configuration_errors(
                    node_id=node.id,
                    inputs=node.inputs,
                )
            )
    diagnostics.errors.extend(generic_code_errors(graph, changes.touched_code_node_ids))
    diagnostics.warnings.extend(graph_warnings(graph))
    port_errors = edge_port_errors(graph, definitions)
    diagnostics.errors.extend(port_errors)
    # Pipeline validation assumes known ports and may ignore an unknown target input.
    if not port_errors:
        diagnostics.errors.extend(pipeline_errors(graph, project))
    return diagnostics

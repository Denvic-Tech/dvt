from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from src.exceptions import DependencyCycleError, NodeInputError, NodeNotFoundError
from src.logger import logger
from src.modules.sql_template import (
    CallbackSQLExpressionEvaluator,
    SQLTemplateError,
    SQLTemplateRenderRequest,
    build_render_sql_template_use_case,
)
from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputLinkValue,
    iter_node_input_link_values,
    parse_node_input_value,
    resolve_node_input_value,
)
from src.node_dsl.input_expressions import evaluate_input_expression
from src.node_dsl.node_typing import IO, contains_exact_io
from src.node_dsl.runtime.connections import resolve_sql_dialect_name
from src.node_dsl.types import NodeOutput
from src.node_dsl.variables import is_unresolved_value, make_unresolved_value
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.types import Pipeline
from src.schemas.internal import NodeData

if TYPE_CHECKING:
    from src.schemas.node_definition import NodeDefinition


def _iter_link_values(link_value: Any) -> Iterable[NodeInputLinkValue]:
    return iter_node_input_link_values(link_value)

def topological_sort(
        pipeline: Pipeline,
        target_nodes: list[str] | None = None
) -> list[str]:
    """
    Выполняет топологическую сортировку узлов пайплайна.

    Args:
        pipeline: Словарь {node_id: NodeData}.
        target_nodes: Список ID целевых узлов (если None, сортирует весь граф).

    Returns:
        Список ID узлов в топологическом порядке.

    Raises:
        DependencyCycleError: Если в графе обнаружен цикл.
        NodeNotFoundError: Если целевой узел не найден.
    """
    logger.debug(f"Performing topological sort. Target nodes: {target_nodes}")
    graph: dict[str, set[str]] = {node_id: set() for node_id in pipeline}
    in_degree: dict[str, int] = {node_id: 0 for node_id in pipeline}

    # Строим граф зависимостей и считаем входящие степени
    for node_id, node_data in pipeline.items():
        for input_data in node_data.inputs.values():
            for lv in _iter_link_values(input_data):
                source_node_id = lv.node_id
                if source_node_id in pipeline:
                    if node_id not in graph[source_node_id]:
                        graph[source_node_id].add(node_id)
                        in_degree[node_id] += 1
                else:
                    # Это может быть нормально, если узел ссылается на внешний источник,
                    # но для валидации пайплайна это ошибка.
                    logger.warning(
                        f"Node ID={node_id} links to non-existent source node ID='{source_node_id}'."
                    )
                    # Не выбрасываем ошибку здесь, валидация должна это проверить

    if target_nodes:
        for node_id in target_nodes:
            if node_id not in pipeline:
                raise NodeNotFoundError(f"Target node '{node_id}' not found in pipeline.")

    in_degree_work: dict[str, int] = in_degree.copy()
    queue = deque([node_id for node_id, degree in in_degree_work.items() if degree == 0])
    full_order: list[str] = []

    while queue:
        node_id = queue.popleft()
        full_order.append(node_id)

        for neighbor_id in graph.get(node_id, set()):
            in_degree_work[neighbor_id] -= 1
            if in_degree_work[neighbor_id] == 0:
                queue.append(neighbor_id)

    if len(full_order) != len(pipeline):
        remaining_nodes = set(pipeline.keys()) - set(full_order)
        logger.error(f"Cycle detected in the pipeline graph. Remaining nodes: {remaining_nodes}")
        raise DependencyCycleError(f"Cycle detected involving nodes: {remaining_nodes}")

    if not target_nodes:
        logger.debug(f"Topological sort successful. Order: {full_order}")
        return full_order

    nodes_to_process = find_all_dependencies(pipeline, target_nodes)
    logger.debug(f"Dependencies for {target_nodes}: {nodes_to_process}")

    ordered_dependencies = [
        node_id
        for node_id in full_order
        if node_id in nodes_to_process
    ]

    logger.debug(f"Topological sort successful. Order: {ordered_dependencies}")
    return ordered_dependencies


def find_all_dependencies(pipeline: Pipeline, target_nodes: list[str]) -> set[str]:
    """
    Находит все узлы, от которых зависят target_nodes (включая сами target_nodes).

    Args:
        pipeline: Словарь {node_id: NodeData}.
        target_nodes: Список ID целевых узлов.

    Returns:
        Множество ID всех зависимых узлов.
    """
    dependencies: set[str] = set()
    queue = deque(target_nodes)
    visited: set[str] = set()

    while queue:
        node_id = queue.popleft()
        if node_id in visited or node_id not in pipeline:
            continue
        visited.add(node_id)
        dependencies.add(node_id)

        node_data = pipeline[node_id]
        for input_data in node_data.inputs.values():
            for lv in _iter_link_values(input_data):
                source_node_id = lv.node_id
                if source_node_id not in visited:
                    queue.append(source_node_id)

    return dependencies


def find_all_dependents(pipeline: Pipeline, source_nodes: list[str]) -> set[str]:
    """
    Находит все узлы, которые зависят от source_nodes (включая сами source_nodes).

    Args:
        pipeline: Словарь {node_id: NodeData}.
        source_nodes: Список ID исходных узлов.

    Returns:
        Множество ID всех downstream-зависимых узлов.
    """
    dependents_graph: dict[str, set[str]] = {node_id: set() for node_id in pipeline}
    for node_id, node_data in pipeline.items():
        for input_data in node_data.inputs.values():
            for lv in _iter_link_values(input_data):
                if lv.node_id in pipeline:
                    dependents_graph[lv.node_id].add(node_id)

    dependents: set[str] = set()
    queue = deque(source_nodes)
    visited: set[str] = set()

    while queue:
        node_id = queue.popleft()
        if node_id in visited or node_id not in pipeline:
            continue

        visited.add(node_id)
        dependents.add(node_id)

        for dependent_node_id in dependents_graph.get(node_id, set()):
            if dependent_node_id not in visited:
                queue.append(dependent_node_id)

    return dependents


def _is_variable_input(input_def: Any) -> bool:
    return contains_exact_io(input_def.type, IO.VARIABLE)


def _is_signal_input(input_def: Any) -> bool:
    return contains_exact_io(input_def.type, IO.SIGNAL)


def _iter_variable_items(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("name"), str) and value["name"]:
            return [(value["name"], value)]
        return [
            (key, item)
            for key, item in value.items()
            if isinstance(key, str) and key
        ]

    variable_name = getattr(value, "name", None)
    if isinstance(variable_name, str) and variable_name:
        return [(variable_name, value)]

    return []


def _is_empty_variable_payload(value: Any) -> bool:
    return isinstance(value, dict) and not value


def _merge_variable_items(
        *,
        target: dict[str, Any],
        variable_items: list[tuple[str, Any]],
) -> None:
    for var_name, var_obj in variable_items:
        target[var_name] = var_obj


def _collect_linked_variables(
        node_id: str,
        node_def: "NodeDefinition",
        node_data: NodeData,
        node_outputs: dict[str, dict[str, NodeOutput]],
) -> dict[str, Any]:
    linked_variables: dict[str, Any] = {}

    for input_name, input_data in node_data.inputs.items():
        input_def = node_def.input_definitions.get(input_name)
        if not input_def or not _is_variable_input(input_def):
            continue

        link_values = list(_iter_link_values(input_data))
        if not link_values:
            continue

        for lv in link_values:
            source_node_id = lv.node_id
            source_output_name = lv.output_name

            if source_node_id not in node_outputs or source_output_name not in node_outputs[source_node_id]:
                raise NodeInputError(
                    f"Node {node_id}: Missing output '{source_output_name}' "
                    f"from source node '{source_node_id}' for input '{input_name}'."
                )

            var_payload = node_outputs[source_node_id][source_output_name].value
            if _is_empty_variable_payload(var_payload):
                continue
            variable_items = _iter_variable_items(var_payload)
            if not variable_items:
                raise NodeInputError(
                    f"Node {node_id}: Variable input '{input_name}' expects variable outputs."
                )

            _merge_variable_items(
                target=linked_variables,
                variable_items=variable_items,
            )

    return linked_variables


def collect_variable_source_node_ids(
        node_def: "NodeDefinition",
        node_data: NodeData,
) -> set[str]:
    source_node_ids: set[str] = set()

    for input_name, input_data in node_data.inputs.items():
        input_def = node_def.input_definitions.get(input_name)
        if not input_def or not _is_variable_input(input_def):
            continue

        for lv in _iter_link_values(input_data):
            source_node_ids.add(lv.node_id)

    return source_node_ids


def build_node_kwargs(
        node_id: str,
        node_def: "NodeDefinition",
        node_data: NodeData,
        node_outputs: dict[str, dict[str, NodeOutput]],  # {node_id: {output_name: NodeOutput(value=Any)}}
        project_variables: dict[str, Any] | None = None,
        execution_mode: PipelineExecutionMode | None = None,
        node_class: type | None = None,
) -> dict[str, Any]:
    """
    Подготавливает входные данные для узла, используя информацию о выходах других узлов.
    """
    node_kwargs: dict[str, Any] = {}
    deferred_sql_templates: list[tuple[str, NodeInputExpressionValue, Any]] = []
    allow_unresolved = execution_mode == PipelineExecutionMode.METADATA_ONLY
    try:
        linked_variables = _collect_linked_variables(
            node_id=node_id,
            node_def=node_def,
            node_data=node_data,
            node_outputs=node_outputs,
        )
        # Backward compatibility: historically ``input_variables`` exposed the
        # merged runtime variable map (project variables + linked variables),
        # with linked variables taking precedence on name collisions. Keep
        # that view for existing expressions while exposing project variables
        # separately through the new ``project_variables`` namespace.
        legacy_input_variables = dict(project_variables or {})
        legacy_input_variables.update(linked_variables)

        for input_name, input_data in node_data.inputs.items():
            input_def = node_def.input_definitions.get(input_name)
            if not input_def:
                continue  # Пропускаем лишние входы

            attr_name = input_def.attr_name  # Имя атрибута в классе Python
            allow_multi = bool(getattr(input_def, "allow_multiple_connections", False))
            is_variable = _is_variable_input(input_def)
            is_signal = _is_signal_input(input_def)

            link_values = list(_iter_link_values(input_data))
            if link_values:

                if allow_multi and is_variable:
                    variables: dict[str, Any] = {}
                    for lv in link_values:
                        source_node_id = lv.node_id
                        source_output_name = lv.output_name

                        if (source_node_id not in node_outputs
                                or source_output_name not in node_outputs[source_node_id]):
                            raise NodeInputError(
                                f"Node {node_id}: Missing output '{source_output_name}' "
                                f"from source node '{source_node_id}' for input '{input_name}'."
                            )

                        var_payload = node_outputs[source_node_id][source_output_name].value
                        if _is_empty_variable_payload(var_payload):
                            continue
                        variable_items = _iter_variable_items(var_payload)
                        if not variable_items:
                            raise NodeInputError(
                                f"Node {node_id}: Variable input '{input_name}' expects variable outputs."
                            )

                        _merge_variable_items(
                            target=variables,
                            variable_items=variable_items,
                        )

                    node_kwargs[attr_name] = variables
                elif allow_multi and is_signal:
                    for lv in link_values:
                        source_node_id = lv.node_id
                        source_output_name = lv.output_name

                        if (source_node_id not in node_outputs
                                or source_output_name not in node_outputs[source_node_id]):
                            raise NodeInputError(
                                f"Node {node_id}: Missing output '{source_output_name}' "
                                f"from source node '{source_node_id}' for input '{input_name}'."
                            )

                    # Signal links define execution dependencies; value payload is intentionally ignored.
                    node_kwargs[attr_name] = None
                else:
                    if len(link_values) != 1:
                        raise NodeInputError(
                            f"Node {node_id}: Input '{input_name}' does not allow multiple connections."
                        )
                    lv = link_values[0]
                    source_node_id = lv.node_id
                    source_output_name = lv.output_name

                    if (source_node_id not in node_outputs
                            or source_output_name not in node_outputs[source_node_id]):
                        raise NodeInputError(
                            f"Node {node_id}: Missing output '{source_output_name}' "
                            f"from source node '{source_node_id}' for input '{input_name}'."
                        )
                    node_kwargs[attr_name] = node_outputs[source_node_id][source_output_name].value

            else:
                if isinstance(input_data, NodeInputConstantValue):
                    raw_value = input_data.value
                else:
                    raw_value = input_data
                try:
                    field = getattr(node_class, "_input_field_instances", {}).get(attr_name) if node_class else None
                    parsed_value = parse_node_input_value(raw_value)
                    if (
                        getattr(field, "sql_template", False)
                        and isinstance(parsed_value, NodeInputExpressionValue)
                        and parsed_value.expression_kind == "template"
                    ):
                        deferred_sql_templates.append((attr_name, parsed_value, input_def))
                        continue
                    node_kwargs[attr_name] = resolve_node_input_value(
                        raw_value,
                        variables=legacy_input_variables,
                        project_variables=project_variables,
                        target_type=input_def.type,
                        is_list_type=bool(getattr(input_def, "is_list_type", False)),
                        allow_expressions=bool(getattr(input_def, "allow_expressions", True)),
                        expression_policy=getattr(input_def, "expression_policy", None),
                        allow_unresolved=allow_unresolved,
                    )
                except ValueError as err:
                    raise NodeInputError(f"Node {node_id}: {err}") from err

        if deferred_sql_templates:
            connection = node_kwargs.get("connection")
            dialect_name = None
            if connection is not None and not is_unresolved_value(connection):
                dialect_name = getattr(getattr(connection, "dialect", None), "name", None)
                dialect_name = dialect_name or getattr(connection, "type", None)
                if dialect_name is None:
                    dialect_name = resolve_sql_dialect_name(connection)

            def evaluate_expression(expression: str, variables: dict[str, Any], project_values: dict[str, Any]) -> Any:
                def unwrap(value: Any) -> Any:
                    if isinstance(value, dict) and "name" in value and "value" in value:
                        return value["value"]
                    if hasattr(value, "name") and hasattr(value, "value"):
                        return value.value
                    return value

                return evaluate_input_expression(
                    expression=expression,
                    variables={key: unwrap(value) for key, value in variables.items()},
                    project_variables={key: unwrap(value) for key, value in project_values.items()},
                    expression_kind="single",
                    expression_policy="default",
                )

            evaluator = CallbackSQLExpressionEvaluator(evaluate_expression)
            renderer = build_render_sql_template_use_case()
            for attr_name, expression_value, input_def in deferred_sql_templates:
                try:
                    node_kwargs[attr_name] = renderer.execute(
                        SQLTemplateRenderRequest(
                            template=expression_value.value,
                            variables=legacy_input_variables,
                            project_variables=dict(project_variables or {}),
                            dialect_name=dialect_name,
                            expression_evaluator=evaluator,
                        )
                    ).sql
                except (SQLTemplateError, TypeError, ValueError) as err:
                    if allow_unresolved:
                        node_kwargs[attr_name] = make_unresolved_value(
                            reason=str(err),
                            declared_type=input_def.type,
                        )
                    else:
                        raise NodeInputError(f"Node {node_id}: {err}") from err

    except (NodeInputError, KeyError) as e:
        logger.error(f"Error preparing inputs for node ID={node_id}: {e}")
        raise

    return node_kwargs

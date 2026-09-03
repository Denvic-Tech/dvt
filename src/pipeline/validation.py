from typing import Dict, List, Set

from src.exceptions import DependencyCycleError, NodeInputError, NodeNotFoundError
from src.logger import logger
from src.node_dsl import registry
from src.node_dsl.constants import NodeInputNames
from src.node_dsl.core.input_values import iter_node_input_link_values
from src.node_dsl.node_typing import IO
from src.pipeline.graph_utils import topological_sort
from src.pipeline.types import Pipeline
from src.schemas.internal import (
    PipelineValidationErrorInfo,
    PipelineValidationNodeErrorInfo,
    PipelineValidationResult,
)


def validate_pipeline(
        pipeline: Pipeline
) -> PipelineValidationResult:
    """
    Валидирует весь пайплайн (граф).

    Возвращает:
        - is_valid (bool): True, если пайплайн валиден.
        - error_info (Optional[Dict]): Информация об общей ошибке валидации (если is_valid=False).
        - target_nodes (List[str]): Список ID узлов с OUTPUT_NODE=True.
        - node_errors (Optional[Dict]): Словарь ошибок для конкретных узлов {node_id: error_details} (если is_valid=False).
    """
    if not pipeline:
        return PipelineValidationResult(
            is_valid=False,
            error_info=PipelineValidationErrorInfo(message="Pipeline is empty."),
            target_nodes=[],
            node_errors={},
        )

    node_errors: Dict[str, PipelineValidationNodeErrorInfo] = {}
    target_nodes: List[str] = []
    all_node_ids: Set[str] = set(pipeline.keys())

    # 1. Проверка существования классов узлов и сбор output_nodes
    for node_id, node_data in pipeline.items():
        try:
            node_class = registry.get_node(node_data.name)
            if node_class.OUTPUT_NODE:
                target_nodes.append(node_id)

        except NodeNotFoundError as e:
            logger.error(f"Validation Error (Node ID={node_id}): {e}")
            node_errors[node_id] = PipelineValidationNodeErrorInfo(
                message=str(e),
                node_name=node_data.name
            )

    if node_errors:
        return PipelineValidationResult(
            is_valid=False,
            error_info=PipelineValidationErrorInfo(message="One or more node classes not found."),
            target_nodes=target_nodes,
            node_errors=node_errors
        )

    # 2. Проверка на циклы с помощью топологической сортировки
    try:
        # Сортируем весь граф для проверки на циклы
        topological_sort(pipeline)
    except DependencyCycleError as e:
        logger.error(f"Pipeline validation error: {e}")

        # Ошибка цикла затрагивает несколько узлов, возвращаем общую ошибку
        return PipelineValidationResult(
            is_valid=False,
            error_info=PipelineValidationErrorInfo(
                message=str(e),
                details=f"Cycle involves nodes: {e.args[0]}"
            ),
            target_nodes=target_nodes,
            node_errors={}
        )

    except Exception as e:  # Другие ошибки сортировки
        logger.error(f"Pipeline validation Error (Topological Sort): {e}")
        return PipelineValidationResult(
            is_valid=False,
            error_info=PipelineValidationErrorInfo(
                message=f"Graph validation error: {e}",
            ),
            target_nodes=target_nodes,
            node_errors={}
        )

    # 3. Проверка связей и типов
    for node_id, node_data in pipeline.items():
        try:
            node_class = registry.get_node(node_data.name)

            node_inputs = node_class.input_fields()
            for input_name, input_data in node_data.inputs.items():
                node_input = node_inputs.get(input_name)
                if not node_input:
                    # Это может произойти, если пайплайн содержит лишние входы для узла
                    logger.warning(
                        f"Pipeline validation Warning (Node ID={node_id}): "
                        f"Input Name={input_name} not defined for class Type={node_data.name}. "
                        f"Skipping validation for this input."
                    )
                    continue  # Не считаем ошибкой, но логируем

                link_values = list(iter_node_input_link_values(input_data))
                if link_values:
                    if input_name == NodeInputNames.SIGNAL:
                        router_signal_links: Dict[str, Set[str]] = {}
                        for lv in link_values:
                            source_node_data = pipeline.get(lv.node_id)
                            if source_node_data is None:
                                continue
                            source_node_class = registry.get_node(source_node_data.name)
                            if source_node_class.CAN_BE_OUTPUT_NODE:
                                continue
                            router_signal_links.setdefault(lv.node_id, set()).add(lv.output_name)

                        invalid_router_sources = [
                            source_node_id
                            for source_node_id, output_names in router_signal_links.items()
                            if len(output_names) > 1
                        ]
                        if invalid_router_sources:
                            raise NodeInputError(
                                "ConditionalSignalRouter outputs cannot be re-joined into a single "
                                f"signal_in. Invalid source node IDs: {invalid_router_sources}."
                            )

                    for lv in link_values:
                        source_node_id = lv.node_id
                        source_output_name = lv.output_name

                        # Проверка существования исходного узла
                        if source_node_id not in all_node_ids:
                            raise NodeNotFoundError(
                                f"Source node ID={source_node_id} for input Name={input_name} not found in pipeline."
                            )

                        # Проверка существования и типа выхода исходного узла
                        source_node_data = pipeline[source_node_id]
                        source_node_def = registry.get_definition(source_node_data.name)
                        source_output_def = source_node_def.output_definitions.get(source_output_name)

                        if not source_output_def:
                            raise NodeInputError(
                                f"Source output Name={source_output_name} "
                                f"not found on node ID={source_node_id} "
                                f"(class Type={source_node_data.name}) for input Name={input_name}."
                            )

                        # Проверка совместимости типов (используем is_subset для гибкости)
                        input_type_io = (
                            IO(node_input.resolved_type)
                            if isinstance(node_input.resolved_type, str)
                            else node_input.resolved_type
                        )
                        output_type_io = (
                            IO(source_output_def.type)
                            if isinstance(source_output_def.type, str)
                            else source_output_def.type
                        )

                        if not output_type_io.is_subset(input_type_io):
                            raise TypeError(
                                f"Type mismatch for input Name={input_name}. "
                                f"Expected compatible with IO_TYPE={input_type_io} "
                                f"but got IO_TYPE='{output_type_io}' from '{source_node_id}.{source_output_name}'."
                            )

                else:
                    # TODO: Добавить валидацию типа константы, если возможно и необходимо.
                    # Это может быть сложно, т.к. тип константы может зависеть от виджета UI.
                    pass  # Пока пропускаем валидацию констант

        except (NodeNotFoundError, NodeInputError, TypeError) as e:
            logger.error(f"Validation Error (Node ID={node_id}): {e}")
            node_errors[node_id] = PipelineValidationNodeErrorInfo(
                message=str(e),
                node_name=node_data.name
            )
        except Exception as e:  # Неожиданные ошибки
            logger.exception(f"Unexpected Validation Error (Node ID={node_id})")
            node_errors[node_id] = PipelineValidationNodeErrorInfo(
                message=f"Unexpected validation error: {e}",
                node_name=node_data.name
            )

    if node_errors:
        return PipelineValidationResult(
            is_valid=False,
            error_info=PipelineValidationErrorInfo(
                message="Validation failed for one or multiple nodes."
            ),
            target_nodes=target_nodes,
            node_errors=node_errors
        )

    logger.info("Pipeline validation successful.")
    return PipelineValidationResult(
        is_valid=True,
        target_nodes=target_nodes
    )

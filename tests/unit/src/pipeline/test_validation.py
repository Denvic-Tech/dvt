from src.pipeline.validation import validate_pipeline
from src.schemas.internal import NodeData
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue
from src.nodes.testing.simple_input import SimpleInputNode
from src.nodes.tool.conditional_signal_router import ConditionalSignalRouter


def _register_nodes(*node_classes) -> None:
    from src.node_dsl.registry import (
        nodes as nodes_registry,
        definitions as definitions_registry,
        hooks as hooks_registry,
    )

    for node_cls in node_classes:
        if node_cls.__name__ not in nodes_registry.get_all():
            nodes_registry.add(node_cls)
        if node_cls.__name__ not in definitions_registry.NODE_DEFINITIONS:
            definitions_registry.build(node_cls)
        hooks_registry.build(node_cls)


def build_simple_pipeline():
    from src.nodes.testing.simple_input import SimpleInputNode
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    return {
        "simple_input": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="hello")},
        ),
        "simple_output": NodeData(
            name="SimpleOutputNode",
            inputs={
                "value_final": NodeInputLinkValue(node_id="simple_input", output_name="value_out")
            },
        ),
    }


def test_validate_pipeline_success():
    result = validate_pipeline(build_simple_pipeline())
    assert result.is_valid is True
    assert result.error_info is None
    assert result.target_nodes == ["simple_output"]


def test_validate_pipeline_with_unknown_node():
    pipeline = {
        "unknown": NodeData(
            name="TotallyMissingNode",
            inputs={},
        )
    }
    result = validate_pipeline(pipeline)
    assert result.is_valid is False
    assert result.error_info is not None
    assert "unknown" in result.node_errors


def test_validate_pipeline_detects_cycle():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    pipeline = {
        "node_a": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputLinkValue(node_id="node_b", output_name="value_out")},
        ),
        "node_b": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputLinkValue(node_id="node_a", output_name="value_out")},
        ),
    }

    result = validate_pipeline(pipeline)
    assert result.is_valid is False
    assert result.error_info is not None
    assert "Cycle" in result.error_info.message


def test_validate_pipeline_detects_missing_output():
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleInputNode, SimpleOutputNode)

    pipeline = {
        "source": NodeData(
            name="SimpleInputNode",
            inputs={"value_in": NodeInputConstantValue(value="text")},
        ),
        "consumer": NodeData(
            name="SimpleOutputNode",
            inputs={"value_final": NodeInputLinkValue(node_id="source", output_name="missing")},
        ),
    }

    result = validate_pipeline(pipeline)
    assert result.is_valid is False
    assert result.error_info is not None
    assert result.node_errors
    mismatch = next(iter(result.node_errors.values()))
    assert "not found" in mismatch.message.lower()

import pytest

from src import enums
from src.exceptions import NodeInputError
from src.node_dsl.core.input_values import NodeInputLinkValue, NodeInputConstantValue
from src.pipeline.graph_utils import build_node_kwargs, topological_sort, find_all_dependents
from src.schemas.internal.node_data import NodeData
from src.node_dsl.types import NodeOutput
from src.schemas.node_definition import InputDefinitionModel, NodeDefinition
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import VariableOutput


def _build_constant_input_node_definition() -> NodeDefinition:
    return NodeDefinition(
        input_definitions={
            "value_in": InputDefinitionModel(
                name="value_in",
                attr_name="value_in",
                display_name="value_in",
                type=IO.STRING,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=False,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                force_input=None,
                widget=None,
                schema=None,
                allow_multiple_connections=False,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )


def _build_constant_and_variables_node_definition() -> NodeDefinition:
    base = _build_constant_input_node_definition()
    return base.model_copy(
        update={
            "input_definitions": {
                **base.input_definitions,
                "input_variables": InputDefinitionModel(
                    name="input_variables",
                    attr_name="input_variables",
                    display_name="input_variables",
                    type=IO.VARIABLE,
                    is_list_type=False,
                    is_literal_type=False,
                    options=None,
                    optional=True,
                    is_hidden=False,
                    description=None,
                    default=None,
                    multiline=None,
                    metadata_source_field=None,
                    min_value=None,
                    max_value=None,
                    step=None,
                    round_val=None,
                    force_input=None,
                    widget=None,
                    schema=None,
                    allow_multiple_connections=True,
                ),
            }
        }
    )


def test_topological_sort_returns_only_target_dependencies():
    pipeline = {
        "main_source": NodeData(name="SourceNode", inputs={}),
        "output_node": NodeData(
            name="OutputNode",
            inputs={"data": NodeInputLinkValue(node_id="main_source", output_name="result")},
        ),
        "orphan_source": NodeData(name="OrphanSource", inputs={}),
        "orphan_child": NodeData(
            name="OrphanChild",
            inputs={"data": NodeInputLinkValue(node_id="orphan_source", output_name="result")},
        ),
        "standalone": NodeData(name="Standalone", inputs={}),
    }

    order = topological_sort(pipeline, target_nodes=["output_node"])

    assert order == ["main_source", "output_node"]


def test_topological_sort_supports_multi_link_inputs():
    pipeline = {
        "a": NodeData(name="A", inputs={}),
        "b": NodeData(name="B", inputs={}),
        "c": NodeData(
            name="C",
            inputs={
                "input_variables": [
                    NodeInputLinkValue(node_id="a", output_name="x"),
                    NodeInputLinkValue(node_id="b", output_name="y"),
                ]
            },
        ),
    }

    order = topological_sort(pipeline)

    assert order == ["a", "b", "c"]


def test_find_all_dependents_returns_downstream_subgraph():
    pipeline = {
        "source": NodeData(name="SourceNode", inputs={}),
        "mid": NodeData(
            name="MidNode",
            inputs={"data": NodeInputLinkValue(node_id="source", output_name="result")},
        ),
        "target": NodeData(
            name="TargetNode",
            inputs={"data": NodeInputLinkValue(node_id="mid", output_name="result")},
        ),
        "other": NodeData(name="Standalone", inputs={}),
    }

    dependents = find_all_dependents(pipeline, ["mid"])

    assert dependents == {"mid", "target"}


def test_build_node_kwargs_collects_multiple_variable_links_into_dict():
    node_def = NodeDefinition(
        input_definitions={
            "input_variables": InputDefinitionModel(
                name="input_variables",
                attr_name="input_variables",
                display_name="input_variables",
                type=IO.VARIABLE,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                force_input=None,
                widget=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "input_variables": [
                NodeInputLinkValue(node_id="v1", output_name="output_variables"),
                NodeInputLinkValue(node_id="v2", output_name="output_variables"),
            ]
        },
    )

    out1 = VariableOutput(name="x", type=IO.STRING, value="1")
    out2 = VariableOutput(name="y", type=IO.STRING, value="2")
    node_outputs = {
        "v1": {"output_variables": NodeOutput(value={"x": out1})},
        "v2": {"output_variables": NodeOutput(value={"y": out2})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["input_variables"] == {"x": out1, "y": out2}


def test_build_node_kwargs_accepts_output_variables_mapping_payload():
    node_def = NodeDefinition(
        input_definitions={
            "input_variables": InputDefinitionModel(
                name="input_variables",
                attr_name="input_variables",
                display_name="input_variables",
                type=IO.VARIABLE,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                force_input=None,
                widget=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={"input_variables": NodeInputLinkValue(node_id="vars", output_name="output_variables")},
    )

    out1 = VariableOutput(name="x", type=IO.STRING, value="1")
    out2 = VariableOutput(name="y", type=IO.STRING, value="2")
    node_outputs = {
        "vars": {"output_variables": NodeOutput(value={"x": out1, "y": out2})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["input_variables"] == {"x": out1, "y": out2}


def test_build_node_kwargs_accepts_empty_output_variables_mapping_payload():
    node_def = NodeDefinition(
        input_definitions={
            "input_variables": InputDefinitionModel(
                name="input_variables",
                attr_name="input_variables",
                display_name="input_variables",
                type=IO.VARIABLE,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                force_input=None,
                widget=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={"input_variables": NodeInputLinkValue(node_id="vars", output_name="output_variables")},
    )
    node_outputs = {
        "vars": {"output_variables": NodeOutput(value={})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["input_variables"] == {}


def test_build_node_kwargs_skips_empty_variable_sources_in_multi_link_payload():
    node_def = NodeDefinition(
        input_definitions={
            "input_variables": InputDefinitionModel(
                name="input_variables",
                attr_name="input_variables",
                display_name="input_variables",
                type=IO.VARIABLE,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                force_input=None,
                widget=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "input_variables": [
                NodeInputLinkValue(node_id="empty", output_name="output_variables"),
                NodeInputLinkValue(node_id="vars", output_name="output_variables"),
            ]
        },
    )
    out1 = VariableOutput(name="x", type=IO.STRING, value="1")
    node_outputs = {
        "empty": {"output_variables": NodeOutput(value={})},
        "vars": {"output_variables": NodeOutput(value={"x": out1})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["input_variables"] == {"x": out1}


def test_build_node_kwargs_last_duplicate_variable_wins():
    node_def = NodeDefinition(
        input_definitions={
            "input_variables": InputDefinitionModel(
                attr_name="input_variables",
                display_name="input_variables",
                type=IO.VARIABLE,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "input_variables": [
                NodeInputLinkValue(node_id="v1", output_name="output_variables"),
                NodeInputLinkValue(node_id="v2", output_name="output_variables"),
            ]
        },
    )

    out1 = VariableOutput(name="x", type=IO.STRING, value="1")
    out2 = VariableOutput(name="x", type=IO.STRING, value="2")
    node_outputs = {
        "v1": {"output_variables": NodeOutput(value={"x": out1})},
        "v2": {"output_variables": NodeOutput(value={"x": out2})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["input_variables"] == {"x": out2}


def test_build_node_kwargs_accepts_multiple_signal_links():
    node_def = NodeDefinition(
        input_definitions={
            "signal_in": InputDefinitionModel(
                attr_name="signal_in",
                display_name="signal_in",
                type=IO.SIGNAL,
                is_list_type=False,
                is_literal_type=False,
                options=None,
                optional=True,
                is_hidden=False,
                description=None,
                default=None,
                multiline=None,
                metadata_source_field=None,
                min_value=None,
                max_value=None,
                step=None,
                round_val=None,
                schema=None,
                allow_multiple_connections=True,
            )
        },
        output_definitions={},
        name="ConsumerNode",
        emoji=None,
        display_name="ConsumerNode",
        description="",
        python_module="tests",
        category="Tests",
        category_color="#6366F1",
        tags=[],
        type=enums.NodeType.BASE,
        output_node=False,
        deprecated=False,
        experimental=False,
        visible=True,
        additional_schema=None,
    )

    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "signal_in": [
                NodeInputLinkValue(node_id="s1", output_name="signal_out"),
                NodeInputLinkValue(node_id="s2", output_name="signal_out"),
            ]
        },
    )

    node_outputs = {
        "s1": {"signal_out": NodeOutput(value="tick-1")},
        "s2": {"signal_out": NodeOutput(value="tick-2")},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
    )

    assert kwargs["signal_in"] is None


def test_build_node_kwargs_resolves_project_variable_constant():
    node_def = _build_constant_input_node_definition()
    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "value_in": NodeInputConstantValue(
                value={"__dvt_type": "expr", "value": "message", "expression_kind": "single"},
            )
        },
    )

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs={},
        project_variables={"message": "resolved value"},
    )

    assert kwargs["value_in"] == "resolved value"


def test_build_node_kwargs_resolves_explicit_project_variable_namespace():
    node_def = _build_constant_input_node_definition()
    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "value_in": NodeInputConstantValue(
                value={
                    "__dvt_type": "expr",
                    "value": "project_variables.message",
                    "expression_kind": "single",
                },
            )
        },
    )

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs={},
        project_variables={"message": "project value"},
    )

    assert kwargs["value_in"] == "project value"


def test_build_node_kwargs_keeps_explicit_namespaces_when_names_collide():
    node_def = _build_constant_and_variables_node_definition()
    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "value_in": NodeInputConstantValue(
                value={
                    "__dvt_type": "expr",
                    "value": "project_variables.message ~ ':' ~ input_variables.message ~ ':' ~ message",
                    "expression_kind": "single",
                },
            ),
            "input_variables": NodeInputLinkValue(
                node_id="vars",
                output_name="output_variables",
            ),
        },
    )
    linked = VariableOutput(name="message", type=IO.STRING, value="input")

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs={"vars": {"output_variables": NodeOutput(value={"message": linked})}},
        project_variables={"message": "project"},
    )

    assert kwargs["value_in"] == "project:input:input"


def test_build_node_kwargs_resolves_linked_create_variable_before_project_variable():
    node_def = _build_constant_and_variables_node_definition()
    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "value_in": NodeInputConstantValue(
                value={"__dvt_type": "expr", "value": "message", "expression_kind": "single"},
            ),
            "input_variables": [
                NodeInputLinkValue(node_id="v1", output_name="output_variables"),
                NodeInputLinkValue(node_id="v2", output_name="output_variables"),
            ],
        },
    )

    out1 = VariableOutput(name="message", type=IO.STRING, value="from_linked_create_variable")
    out2 = VariableOutput(name="other", type=IO.STRING, value="unused")
    node_outputs = {
        "v1": {"output_variables": NodeOutput(value={"message": out1})},
        "v2": {"output_variables": NodeOutput(value={"other": out2})},
    }

    kwargs = build_node_kwargs(
        node_id="consumer",
        node_def=node_def,
        node_data=node_data,
        node_outputs=node_outputs,
        project_variables={"message": "from_project_variable"},
    )

    assert kwargs["value_in"] == "from_linked_create_variable"
    assert kwargs["input_variables"] == {"message": out1, "other": out2}


def test_build_node_kwargs_raises_for_missing_project_variable():
    node_def = _build_constant_input_node_definition()
    node_data = NodeData(
        name="ConsumerNode",
        inputs={
            "value_in": NodeInputConstantValue(
                value={"__dvt_type": "expr", "value": "missing_key", "expression_kind": "single"},
            )
        },
    )

    with pytest.raises(NodeInputError, match="Variable 'missing_key' not found"):
        build_node_kwargs(
            node_id="consumer",
            node_def=node_def,
            node_data=node_data,
            node_outputs={},
            project_variables={},
        )

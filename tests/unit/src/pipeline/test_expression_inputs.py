from src import enums
from src.node_dsl.field import InputField
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import UnresolvedValue
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.graph_utils import build_node_kwargs
from src.schemas.internal import NodeData
from src.schemas.node_definition import InputDefinitionModel, NodeDefinition

TEMPLATE_NODE_DEFINITION = NodeDefinition(
    input_definitions={
        "sql": InputDefinitionModel(
            attr_name="sql",
            display_name="sql",
            type=IO.STRING,
            is_list_type=False,
            is_literal_type=False,
            options=None,
            optional=False,
            is_hidden=False,
            description=None,
            default=None,
            multiline=True,
            metadata_source_field=None,
            min_value=None,
            max_value=None,
            step=None,
            round_val=None,
            force_input=None,
            widget=None,
            schema=None,
            allow_multiple_connections=False,
            allow_new=False,
            allow_expressions=True,
            expression_policy="default",
            force_handle_visible=False,
        )
    },
    output_definitions={},
    name="TemplateConsumer",
    emoji=None,
    display_name="TemplateConsumer",
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


SINGLE_LINE_INT_NODE_DEFINITION = NodeDefinition(
    input_definitions={
        "limit": InputDefinitionModel(
            attr_name="limit",
            display_name="limit",
            type=IO.INT,
            is_list_type=False,
            is_literal_type=False,
            options=None,
            optional=False,
            is_hidden=False,
            description=None,
            default=None,
            multiline=False,
            metadata_source_field=None,
            min_value=None,
            max_value=None,
            step=None,
            round_val=None,
            force_input=None,
            widget=None,
            schema=None,
            allow_multiple_connections=False,
            allow_new=False,
            allow_expressions=True,
            expression_policy="default",
            force_handle_visible=False,
        )
    },
    output_definitions={},
    name="LimitConsumer",
    emoji=None,
    display_name="LimitConsumer",
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


SINGLE_LINE_STRING_LIST_NODE_DEFINITION = SINGLE_LINE_INT_NODE_DEFINITION.model_copy(
    update={
        "input_definitions": {
            "partition_on": SINGLE_LINE_INT_NODE_DEFINITION.input_definitions["limit"].model_copy(
                update={
                    "attr_name": "partition_on",
                    "display_name": "partition_on",
                    "type": IO.STRING,
                    "is_list_type": True,
                    "optional": True,
                }
            )
        },
        "name": "StringListConsumer",
        "display_name": "StringListConsumer",
    }
)


def test_build_node_kwargs_resolves_template_expression_for_string_input():
    node_data = NodeData(
        name="TemplateConsumer",
        inputs={
            "sql": {
                "__dvt_type": "expr",
                "value": "SELECT * FROM {{ input_variables.target_table }}",
                "expression_kind": "template",
            }
        },
    )

    kwargs = build_node_kwargs(
        node_id="template-consumer",
        node_def=TEMPLATE_NODE_DEFINITION,
        node_data=node_data,
        node_outputs={},
        project_variables={"target_table": "warehouse.events"},
    )

    assert kwargs["sql"] == "SELECT * FROM warehouse.events"


def test_build_node_kwargs_resolves_single_line_expression_for_int_input():
    node_data = NodeData(
        name="LimitConsumer",
        inputs={
            "limit": {
                "__dvt_type": "expr",
                "value": "input_variables.base_limit + 5",
                "expression_kind": "single",
            }
        },
    )

    kwargs = build_node_kwargs(
        node_id="limit-consumer",
        node_def=SINGLE_LINE_INT_NODE_DEFINITION,
        node_data=node_data,
        node_outputs={},
        project_variables={"base_limit": 10},
    )

    assert kwargs["limit"] == 15


def test_build_node_kwargs_resolves_single_line_expression_for_string_list_input():
    node_data = NodeData(
        name="StringListConsumer",
        inputs={
            "partition_on": {
                "__dvt_type": "expr",
                "value": "partition_columns",
                "expression_kind": "single",
            }
        },
    )

    kwargs = build_node_kwargs(
        node_id="string-list-consumer",
        node_def=SINGLE_LINE_STRING_LIST_NODE_DEFINITION,
        node_data=node_data,
        node_outputs={},
        project_variables={"partition_columns": ["country", "date"]},
    )

    assert kwargs["partition_on"] == ["country", "date"]


def test_build_node_kwargs_returns_unresolved_for_missing_variable_in_metadata_mode():
    node_data = NodeData(
        name="TemplateConsumer",
        inputs={
            "sql": {
                "__dvt_type": "expr",
                "value": "SELECT * FROM {{ input_variables.target_table }}",
                "expression_kind": "template",
            }
        },
    )

    kwargs = build_node_kwargs(
        node_id="template-consumer",
        node_def=TEMPLATE_NODE_DEFINITION,
        node_data=node_data,
        node_outputs={},
        project_variables={},
        execution_mode=PipelineExecutionMode.METADATA_ONLY,
    )

    assert isinstance(kwargs["sql"], UnresolvedValue)


def test_build_node_kwargs_renders_marked_sql_template_after_connection_resolution():
    class _Connection:
        dialect = type("Dialect", (), {"name": "clickhouse"})()

    sql_definition = TEMPLATE_NODE_DEFINITION.model_copy(
        update={
            "input_definitions": {
                **TEMPLATE_NODE_DEFINITION.input_definitions,
                "connection": TEMPLATE_NODE_DEFINITION.input_definitions["sql"].model_copy(
                    update={"attr_name": "connection", "display_name": "connection"}
                ),
            }
        }
    )
    marker = InputField(sql_template=True)
    node_class = type("SQLTemplateNode", (), {"_input_field_instances": {"sql": marker}})
    node_data = NodeData(
        name="SQLTemplateNode",
        inputs={
            "connection": {"__dvt_type": "const", "value": _Connection()},
            "sql": {
                "__dvt_type": "expr",
                "value": "INSERT INTO errors(message) VALUES ('{{ input_variables.message }}')",
                "expression_kind": "template",
            },
        },
    )

    kwargs = build_node_kwargs(
        node_id="sql-template-node",
        node_def=sql_definition,
        node_data=node_data,
        node_outputs={},
        project_variables={"message": "Unknown table 'my_table_1'"},
        node_class=node_class,
    )

    assert kwargs["sql"] == "INSERT INTO errors(message) VALUES ('Unknown table ''my_table_1''')"

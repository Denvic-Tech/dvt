from src import enums
from src.node_dsl import BaseNode, InputField, OutputField
from src.node_dsl.input_expressions import ExpressionPolicy
from src.node_dsl.registry import definitions as definitions_registry


class ExpressionAwareNode(BaseNode):
    TITLE = "Expression Aware Node"

    sql: str = InputField(
        multiline=True,
        expression_policy="default",
    )
    output: str = OutputField()

    def process(self) -> None:
        self.output = self.sql


class PythonLocalsNode(BaseNode):
    TITLE = "Python Locals Node"

    code: str = InputField(
        multiline=True,
        allow_expressions=False,
        expression_policy="default",
    )
    output: str = OutputField()

    def process(self) -> None:
        self.output = self.code


def test_node_definition_exposes_expression_metadata_for_template_inputs():
    definition = definitions_registry._create_node_base_definition(ExpressionAwareNode)

    sql_input = definition.input_definitions["sql"]

    assert sql_input.allow_expressions is True
    assert sql_input.expression_policy == "default"


def test_node_definition_exposes_disabled_expressions_for_python_code_inputs():
    definition = definitions_registry._create_node_base_definition(PythonLocalsNode)

    code_input = definition.input_definitions["code"]

    assert code_input.allow_expressions is False
    assert code_input.expression_policy == "default"
    assert definition.type == enums.NodeType.BASE


def test_node_definition_serializes_custom_expression_policy_name():
    class CustomPolicyNode(BaseNode):
        TITLE = "Custom Policy Node"

        value: str = InputField(
            expression_policy=ExpressionPolicy(
                name="restricted",
                allowed_filters=frozenset({"lower"}),
            )
        )
        output: str = OutputField()

        def process(self) -> None:
            self.output = self.value

    definition = definitions_registry._create_node_base_definition(CustomPolicyNode)

    value_input = definition.input_definitions["value"]

    assert value_input.allow_expressions is True
    assert value_input.expression_policy == "restricted"

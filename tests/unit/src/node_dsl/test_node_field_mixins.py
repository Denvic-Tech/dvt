import dask.dataframe as dd
import pytest

from src.node_dsl import BaseNode, DFOutputBaseNode, InputField, NodeFieldsMixin, OutputField
from src.node_dsl.hooks import on_validation


class _InputFieldMixin(NodeFieldsMixin):
    mixin_input: str = InputField(default="from-mixin")


class _OutputFieldMixin(NodeFieldsMixin):
    mixin_output: str = OutputField()


class _RightPrecedenceMixin(NodeFieldsMixin):
    shared_value: str = InputField(default="right")


class _LeftPrecedenceMixin(NodeFieldsMixin):
    shared_value: str = InputField(default="left")


class _DisabledOutputMixin(NodeFieldsMixin):
    disabled_output: str = OutputField()


class _DataFrameOutputMixin(NodeFieldsMixin):
    output: dd.DataFrame = OutputField()


class _ValidationHookMixin:
    @on_validation
    def validate_from_regular_mixin(self) -> None:
        self.validation_hook_called = True


class _PlainFieldMixin:
    plain_input: str = InputField(default="ignored")


def test_node_fields_mixin_materializes_inherited_fields() -> None:
    class ExampleNode(_InputFieldMixin, _OutputFieldMixin, BaseNode):
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = self.mixin_input
            self.mixin_output = self.mixin_input

    assert "mixin_input" in ExampleNode._input_field_instances
    assert "mixin_output" in ExampleNode._output_field_instances
    assert getattr(ExampleNode, "mixin_input") == "from-mixin"
    assert getattr(ExampleNode, "mixin_output") is Ellipsis


def test_node_fields_mixin_leftmost_base_has_priority() -> None:
    class ExampleNode(_LeftPrecedenceMixin, _RightPrecedenceMixin, BaseNode):
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = self.shared_value

    assert getattr(ExampleNode, "shared_value") == "left"


def test_node_fields_mixin_concrete_node_field_overrides_mixin() -> None:
    class ExampleNode(_InputFieldMixin, BaseNode):
        mixin_input: str = InputField(default="from-node")
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = self.mixin_input

    assert getattr(ExampleNode, "mixin_input") == "from-node"


def test_non_opt_in_field_mixin_is_ignored() -> None:
    class ExampleNode(_PlainFieldMixin, BaseNode):
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = "ok"

    assert "plain_input" not in ExampleNode._input_field_instances


def test_disabled_outputs_hide_field_mixin_outputs() -> None:
    class ExampleNode(_DisabledOutputMixin, BaseNode):
        DISABLED_OUTPUTS = ["disabled_output"]
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = "ok"

    assert "disabled_output" not in ExampleNode._output_field_instances


def test_df_output_node_accepts_output_field_from_mixin() -> None:
    class ExampleNode(_DataFrameOutputMixin, DFOutputBaseNode):
        def process(self) -> None:
            return None

    assert "output" in ExampleNode._output_field_instances


@pytest.mark.asyncio
async def test_regular_mixin_validation_hook_still_executes() -> None:
    class ExampleNode(_ValidationHookMixin, BaseNode):
        validation_hook_called = False
        node_output: str = OutputField()

        def process(self) -> None:
            self.node_output = "ok"

    node = ExampleNode(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
    )

    await node.validate()

    assert node.validation_hook_called is True

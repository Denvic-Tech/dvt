from types import SimpleNamespace

from src.node_dsl import (
    IO,
    BaseNode,
    ExecutionDateTimePrecision,
    ExecutionSettings,
    InputField,
    OutputField,
)
from src.node_dsl.base_node.mixins import extension_node as extension_node_mixin_module
from src.node_dsl.variables import VariableOutput
from src.pipeline.execution_mode import PipelineExecutionMode


class VariablePortsExampleNode(BaseNode):
    TITLE = "Variable Ports Example Node"

    emitted_variable: IO.VARIABLE = OutputField()
    passthrough_value: str = InputField(default="ok")

    def process(self) -> None:
        self.emitted_variable = VariableOutput(
            name="runtime_value",
            type=IO.STRING,
            value=self.passthrough_value,
            var_type="user",
        )


def test_base_node_normalizes_input_variables_into_output_variables() -> None:
    existing_variable = VariableOutput(
        name="incoming_value",
        type=IO.INT,
        value=10,
        var_type="user",
    )

    node = VariablePortsExampleNode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-variables",
        input_variables={"incoming_value": existing_variable},
    )

    assert node.input_variables == {"incoming_value": existing_variable}
    assert node.output_variables == {"incoming_value": existing_variable}


def test_base_node_refreshes_output_variables_from_variable_output_fields() -> None:
    incoming_variable = VariableOutput(
        name="incoming_value",
        type=IO.INT,
        value=10,
        var_type="user",
    )

    node = VariablePortsExampleNode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-variables",
        input_variables={"incoming_value": incoming_variable},
        passthrough_value="done",
    )

    node.process()
    node._refresh_output_variables()

    assert node.output_variables == {
        "incoming_value": incoming_variable,
        "runtime_value": VariableOutput(
            name="runtime_value",
            type=IO.STRING,
            value="done",
            var_type="user",
        ),
    }


def test_base_node_uses_default_execution_settings() -> None:
    node = VariablePortsExampleNode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-execution-settings",
    )

    assert node.execution_settings == ExecutionSettings()


def test_base_node_from_pipeline_processor_passes_execution_settings() -> None:
    execution_settings = ExecutionSettings(
        datetime_precision=ExecutionDateTimePrecision.SECONDS,
    )
    processor = SimpleNamespace(
        task=SimpleNamespace(
            user_id="user-1",
            project_id="project-1",
            task_id="task-1",
            project_settings=None,
            project_variables=None,
            license_type=None,
            mode=PipelineExecutionMode.FULL,
        ),
        data_store=None,
        data_index_store=None,
        metadata_store=None,
        metadata_index_store=None,
        execution_settings=execution_settings,
    )

    node = VariablePortsExampleNode.from_pipeline_processor(
        pipeline_processor=processor,
        node_id="node-execution-settings",
    )

    assert node.execution_settings is execution_settings


def test_extension_state_resolution_uses_module_name_and_updates_version(monkeypatch) -> None:
    class ExtensionAwareNode(BaseNode):
        TITLE = "Extension Aware Node"
        EXTENSION_NAME = None
        EXTENSION_VERSION = None
        __module__ = "dvt_extensions.sample.nodes.fake"

        def process(self) -> None:
            return None

    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        extension_node_mixin_module,
        "get_all_extensions",
        lambda: {
            "sample": SimpleNamespace(
                name="sample",
                version="1.2.3",
                root_dir=None,
            )
        },
    )
    monkeypatch.setattr(
        extension_node_mixin_module.ExtensionStateManager,
        "get_state",
        lambda extension_name, key="default": (
            calls.append((extension_name, key)) or {"key": key}
        ),
    )

    assert ExtensionAwareNode.get_extension_state("runtime") == {"key": "runtime"}
    assert calls == [("sample", "runtime")]
    assert ExtensionAwareNode.EXTENSION_NAME == "sample"
    assert ExtensionAwareNode.EXTENSION_VERSION == "1.2.3"


def test_extension_state_update_uses_atomic_manager_api(monkeypatch) -> None:
    class ExtensionAwareNode(BaseNode):
        TITLE = "Extension Aware Node"
        EXTENSION_NAME = None
        EXTENSION_VERSION = None
        __module__ = "dvt_extensions.sample.nodes.fake"

        def process(self) -> None:
            return None

    calls: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        extension_node_mixin_module,
        "get_all_extensions",
        lambda: {
            "sample": SimpleNamespace(
                name="sample",
                version="1.2.3",
                root_dir=None,
            )
        },
    )

    def fake_update_state(extension_name, updater, key="default"):
        updated = updater({"counter": 1})
        calls.append((extension_name, key, updated))
        return updated

    monkeypatch.setattr(
        extension_node_mixin_module.ExtensionStateManager,
        "update_state",
        fake_update_state,
    )

    result = ExtensionAwareNode.update_extension_state(
        lambda state: {"counter": state["counter"] + 1},
        key="runtime",
    )

    assert result == {"counter": 2}
    assert calls == [("sample", "runtime", {"counter": 2})]

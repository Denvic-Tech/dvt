from collections import defaultdict
from types import SimpleNamespace

from pydantic import BaseModel, Field

from src.node_dsl import BaseNode, InputField, NodeFieldsMixin
from src.node_dsl.registry import definitions as registry
from src.schemas.node_definition import InputDefinitionModel


class AgentGuidanceMixin(NodeFieldsMixin):
    choice: str = InputField(
        "User-facing choice.", "default",
        agent_description="Inspect the available choices before selecting.",
    )


class AgentGuidanceNode(AgentGuidanceMixin, BaseNode):
    legacy: str | None = InputField(description="Legacy input.")

    def process(self):
        pass


def test_guidance_survives_mixin_and_node_inheritance_without_sharing_fields():
    class Child(AgentGuidanceNode):
        pass

    definition = registry._create_node_base_definition(Child)
    field = definition.input_definitions["choice"]
    assert field.description == "User-facing choice."
    assert field.agent_description == "Inspect the available choices before selecting."
    assert field.default == "default"
    assert field.optional is False
    assert definition.input_definitions["legacy"].agent_description is None

    Child._input_field_instances["choice"].agent_description = "Child-specific guidance."
    assert AgentGuidanceNode._input_field_instances["choice"].agent_description == (
        "Inspect the available choices before selecting."
    )
    assert AgentGuidanceMixin._mixin_input_field_instances["choice"].agent_description == (
        "Inspect the available choices before selecting."
    )


def test_legacy_definition_payload_remains_valid_and_guidance_is_not_localized():
    definition = registry._create_node_base_definition(AgentGuidanceNode)
    payload = definition.input_definitions["choice"].model_dump()
    payload.pop("agent_description")
    restored = InputDefinitionModel.model_validate(payload)
    assert restored.agent_description is None
    schema = InputDefinitionModel.model_json_schema()["properties"]
    assert schema["description"]["i18n"] is True
    assert not schema["agent_description"].get("i18n", False)


def test_registry_localizes_ui_description_but_preserves_agent_guidance(monkeypatch):
    monkeypatch.setattr(registry, "NODE_DEFINITIONS", defaultdict(dict))
    manager = SimpleNamespace(
        get_available_languages=lambda: ["ru"],
        get_translation=lambda lang, node, key, fallback: fallback,
        get_field_translation=lambda lang, node, kind, name, key, fallback: (
            "Подсказка для пользователя" if key == "description" else fallback
        ),
        get_type_translation=lambda lang, value, fallback: fallback,
    )
    monkeypatch.setattr(registry, "get_localization_manager", lambda: manager)
    registry.build(AgentGuidanceNode)
    base = registry.get("AgentGuidanceNode")
    localized = registry.get("AgentGuidanceNode", "ru")
    assert localized.input_definitions["choice"].description == "Подсказка для пользователя"
    assert localized.input_definitions["choice"].agent_description == (
        base.input_definitions["choice"].agent_description
    )
    localized.input_definitions["choice"].agent_description = "Changed copy."
    assert registry.get("AgentGuidanceNode", "ru").input_definitions["choice"].agent_description == (
        base.input_definitions["choice"].agent_description
    )


def test_nested_schema_can_carry_agent_guidance():
    class Settings(BaseModel):
        key: str = Field(
            description="Key column.",
            json_schema_extra={"agent_description": "Inspect key cardinality."},
        )

    class NestedNode(BaseNode):
        settings: Settings = InputField(agent_description="Inspect the nested settings.")

        def process(self):
            pass

    field = registry._create_node_base_definition(NestedNode).input_definitions["settings"]
    assert field.agent_description == "Inspect the nested settings."
    assert field.schema["properties"]["key"]["agent_description"] == "Inspect key cardinality."

from collections import defaultdict
from types import SimpleNamespace

from src.node_dsl.base_node.base import BaseNode
from src.node_dsl.registry import definitions
from src.schemas.node_definition import NodeDefinition


def test_legacy_extension_keeps_emoji_and_defaults_to_no_icon():
    class LegacyIconExtension(BaseNode):
        EXTENSION_NAME = "legacy-icons"
        EMOJI = "legacy"

        def process(self):
            pass

    definition = definitions._create_node_base_definition(LegacyIconExtension)
    assert definition.icon_key is None
    assert definition.emoji == "legacy"
    assert definition.extension_name == "legacy-icons"

    payload = definition.model_dump()
    payload.pop("icon_key")
    assert NodeDefinition.model_validate(payload).icon_key is None


def test_icon_key_is_not_localized_or_restricted_to_builtin_keys(monkeypatch):
    class IconExtension(BaseNode):
        ICON_KEY = "future-extension-icon"
        EMOJI = "legacy"

        def process(self):
            pass

    manager = SimpleNamespace(
        get_available_languages=lambda: ["en", "ru"],
        get_translation=lambda lang, node, field, default: f"{lang}:{default}",
        get_field_translation=lambda lang, node, group, attr, field, default: default,
        get_type_translation=lambda lang, type_, default: default,
    )
    monkeypatch.setattr(definitions, "get_localization_manager", lambda: manager)

    monkeypatch.setattr(definitions, "NODE_DEFINITIONS", defaultdict(dict))
    definitions.build(IconExtension)
    for locale in ("default", "en", "ru"):
        definition = definitions.get("IconExtension", locale)
        assert definition.icon_key == "future-extension-icon"
        assert definition.emoji == "legacy"
    assert definitions.get("IconExtension", "ru").display_name.startswith("ru:")

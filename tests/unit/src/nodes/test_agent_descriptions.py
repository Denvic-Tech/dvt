from collections import defaultdict
from pathlib import Path

import pytest

from src.node_dsl.discovery.packages import discover_builtin_node_packages
from src.node_dsl.registry import definitions as registry

import config

# Discovery includes disabled, experimental, internal, and deprecated packages.
# Do not use the filtered MCP/UI catalog: it would hide coverage gaps.
BUILTIN_PACKAGES = discover_builtin_node_packages(Path(config.PROJECT.NODES_DIR))


@pytest.mark.parametrize("package", BUILTIN_PACKAGES, ids=lambda package: package.node_name)
def test_all_builtin_inputs_publish_agent_guidance_in_every_locale(package, monkeypatch):
    monkeypatch.setattr(registry, "NODE_DEFINITIONS", defaultdict(dict))
    registry.build(package.node_cls)

    fields = package.node_cls._input_field_instances
    assert fields, f"{package.node_name} must include inherited BaseNode inputs"
    for locale in ("default", "en", "ru"):
        definition = registry.get(package.node_name, locale)
        payload = definition.model_dump(mode="json")
        assert set(payload["input_definitions"]) == set(fields)
        for name, field in fields.items():
            guidance = field.agent_description
            assert isinstance(guidance, str) and guidance.strip(), (
                f"{package.node_name}.{name} has no agent_description"
            )
            assert payload["input_definitions"][name]["agent_description"] == guidance

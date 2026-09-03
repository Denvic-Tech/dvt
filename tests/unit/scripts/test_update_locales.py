import json
from copy import deepcopy
from types import SimpleNamespace

from scripts.misc import update_locales


def test_update_nodes_locales_keeps_translations_and_adds_new_data(
    tmp_path,
    monkeypatch,
):
    existing_data = {
        "nodes": {
            "ExistingNode": {
                "display_name": "Существующий перевод",
                "description": None,
                "input_definitions": {
                    "existing_input": {
                        "display_name": "переведенный_вход",
                        "description": "Переведенное описание",
                    },
                },
            },
        },
        "type_mapping": {"CUSTOM": "ПОЛЬЗОВАТЕЛЬСКИЙ"},
    }
    fresh_i18n = {
        "ExistingNode": {
            "display_name": "Existing Node",
            "description": "Fresh description",
            "input_definitions": {
                "existing_input": {
                    "display_name": "existing_input",
                    "display_type": "STRING",
                    "description": "Fresh input description",
                },
                "new_input": {
                    "display_name": "new_input",
                    "display_type": "INTEGER",
                    "description": "New input description",
                },
            },
        },
        "NewNode": {
            "display_name": "New Node",
            "description": "New node description",
        },
    }

    for locale in ("en", "ru"):
        locale_dir = tmp_path / locale
        locale_dir.mkdir()
        (locale_dir / "nodes.json").write_text(
            json.dumps(existing_data, ensure_ascii=False),
            encoding="utf-8",
        )

    definitions = {node_name: object() for node_name in fresh_i18n}
    i18n_by_definition = {
        definitions[node_name]: node_i18n
        for node_name, node_i18n in fresh_i18n.items()
    }
    monkeypatch.setattr(
        update_locales.config,
        "PROJECT",
        SimpleNamespace(LOCALES_DIR=tmp_path),
    )
    monkeypatch.setattr(update_locales, "get_all_definitions", lambda: definitions)
    monkeypatch.setattr(
        update_locales,
        "extract_i18n_fields_as_mapping",
        lambda definition: deepcopy(i18n_by_definition[definition]),
    )

    update_locales.update_nodes_locales()

    for locale in ("en", "ru"):
        updated_data = json.loads((tmp_path / locale / "nodes.json").read_text("utf-8"))
        existing_node = updated_data["nodes"]["ExistingNode"]

        assert existing_node["display_name"] == "Существующий перевод"
        assert existing_node["description"] == "Fresh description"
        assert existing_node["input_definitions"]["existing_input"] == {
            "display_name": "переведенный_вход",
            "description": "Переведенное описание",
            "display_type": "STRING",
        }
        assert existing_node["input_definitions"]["new_input"] == fresh_i18n[
            "ExistingNode"
        ]["input_definitions"]["new_input"]
        assert updated_data["nodes"]["NewNode"] == fresh_i18n["NewNode"]
        assert updated_data["type_mapping"]["CUSTOM"] == "ПОЛЬЗОВАТЕЛЬСКИЙ"

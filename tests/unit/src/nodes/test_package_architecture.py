from pathlib import Path

import config


def test_builtin_node_tree_uses_package_contract() -> None:
    nodes_root = Path(config.PROJECT.NODES_DIR)
    for category in nodes_root.iterdir():
        if category.name.startswith("_") or not category.is_dir():
            continue
        assert (category / "__init__.py").is_file(), category
        public_flat_modules = [
            path for path in category.glob("*.py")
            if path.name != "__init__.py" and not path.name.startswith("_")
        ]
        assert public_flat_modules == [], public_flat_modules
        for child in category.iterdir():
            if child.name.startswith("_") or not child.is_dir():
                continue
            assert (child / "node.yaml").is_file(), child
            assert (child / "__init__.py").is_file(), child

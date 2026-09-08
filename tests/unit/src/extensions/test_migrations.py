from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.extensions.migrations import ExtensionMigrationManager


def test_upgrade_without_migrations_does_not_touch_database(tmp_path: Path) -> None:
    manager = ExtensionMigrationManager(engine=Mock())
    manager.ensure_schema = Mock(return_value="unused")
    extension = SimpleNamespace(
        name="sample-extension",
        root_dir=tmp_path,
        backend=SimpleNamespace(migrations_dir=None),
    )

    manager.upgrade(extension)

    manager.ensure_schema.assert_not_called()

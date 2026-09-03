from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.schema import CreateSchema, DropSchema

from src.db import engine as default_engine
from src.extensions.database import extension_schema_name
from src.extensions.loader import _temporary_sys_path
from src.extensions.registry import RegisteredExtension


def _resolve_migrations_dir(extension: RegisteredExtension) -> Path | None:
    raw = extension.backend.migrations_dir
    if not raw:
        return None
    raw_path = Path(raw)
    if raw_path.is_absolute():
        raise ValueError(f"Extension '{extension.name}' migrations_dir must be relative")
    migrations_dir = (extension.root_dir / raw_path).resolve()
    try:
        migrations_dir.relative_to(extension.root_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            f"Extension '{extension.name}' migrations_dir escapes extension root"
        ) from exc
    if not migrations_dir.is_dir():
        raise FileNotFoundError(
            f"Extension '{extension.name}' migrations dir does not exist: {migrations_dir}"
        )
    versions_dir = migrations_dir / "versions"
    if not versions_dir.is_dir():
        raise FileNotFoundError(
            f"Extension '{extension.name}' migrations directory must contain versions/"
        )
    return migrations_dir


class ExtensionMigrationManager:
    """Runs extension revision scripts inside a host-owned Alembic environment."""

    def __init__(self, engine: Engine = default_engine) -> None:
        self.engine = engine
        self._script_location = Path(__file__).with_name("alembic_runtime")

    def ensure_schema(self, extension_name: str) -> str:
        schema_name = extension_schema_name(extension_name)
        with self.engine.begin() as connection:
            connection.execute(CreateSchema(schema_name, if_not_exists=True))
        return schema_name

    def upgrade(self, extension: RegisteredExtension) -> None:
        schema_name = self.ensure_schema(extension.name)
        migrations_dir = _resolve_migrations_dir(extension)
        if migrations_dir is None:
            return

        cfg = Config()
        cfg.set_main_option("script_location", str(self._script_location))
        cfg.set_main_option("version_locations", str(migrations_dir / "versions"))
        cfg.set_main_option("path_separator", "os")

        with self.engine.connect() as connection:
            quoted = connection.dialect.identifier_preparer.quote(schema_name)
            connection.exec_driver_sql(f"SET search_path TO {quoted}, public")
            connection.commit()
            try:
                cfg.attributes["connection"] = connection
                cfg.attributes["extension_schema"] = schema_name
                with _temporary_sys_path([extension.root_dir]):
                    command.upgrade(cfg, "head")
            finally:
                connection.exec_driver_sql("RESET search_path")
                connection.commit()

    def drop_schema(self, extension_name: str) -> None:
        schema_name = extension_schema_name(extension_name)
        with self.engine.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True, if_exists=True))


__all__ = ["ExtensionMigrationManager"]

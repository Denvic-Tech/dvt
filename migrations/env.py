from logging.config import fileConfig
from typing import Union, Iterable, Optional, List

from alembic import context
from alembic.operations import MigrationScript
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from src.db import engine
import config as project_config
from migrations.revision_ids import next_sequential_revision_id

from src.models import (
    AIAnalysisRequestRecord,  # noqa: F403
    LogRecord,  # noqa: F403
    ExtensionRecord,  # noqa: F403
    OrganizationRecord,  # noqa: F403
    QueueTopicRecord,  # noqa: F403
    UsersTokenRecord,  # noqa: F403
    SQLModel,
)

from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord, GraphEdgeRecord, SubgraphRecord    # noqa: F403
from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord  # noqa: F403
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord  # noqa: F403
from src.modules.app_settings.infra.db_models import AppSettingChangeRecord, AppSettingValueRecord  # noqa: F403
from src.modules.task_execution.infra.db_models import (  # noqa: F403
    TaskDispatchOutboxRecord,
    TaskRecord,
)
from src.modules.user.infra.db_models import UserRecord  # noqa: F403
from src.modules.project.infra.db_models import (
    ProjectRecord,  # noqa: F403
    ProjectFolderRecord,  # noqa: F403
    ProjectScheduleRecord,  # noqa: F403
    ProjectScheduleRunRecord  # noqa: F403
)


def process_revision_directives(
    context: MigrationContext,
    revision: Union[str, Iterable[Optional[str]], Iterable[str]],
    directives: List[MigrationScript],
) -> None:
    migration_script = directives[0]
    script_directory = ScriptDirectory.from_config(context.config)
    revisions = script_directory.walk_revisions()
    migration_script.rev_id = next_sequential_revision_id(
        migration.revision for migration in revisions
    )


def _is_json_type(type_obj: object | None) -> bool:
    json_types = (sa.JSON, postgresql.JSON, postgresql.JSONB)
    if type_obj is None:
        return False
    if isinstance(type_obj, type):
        return issubclass(type_obj, json_types)
    return isinstance(type_obj, json_types)


def _is_json_backed_type_decorator(type_obj: object | None) -> bool:
    if not isinstance(type_obj, sa.types.TypeDecorator):
        return False

    impl = getattr(type_obj, "impl", None)
    seen_impl_ids: set[int] = set()
    while impl is not None and id(impl) not in seen_impl_ids:
        if _is_json_type(impl):
            return True
        seen_impl_ids.add(id(impl))
        impl = getattr(impl, "impl", None)

    return False


def render_item(type_, obj, autogen_context):
    if type_ == "type":
        module = obj.__class__.__module__

        # для типов из sqlmodel.sql.sqltypes
        if module == "sqlmodel.sql.sqltypes":
            autogen_context.imports.add("import sqlmodel.sql.sqltypes")

        if _is_json_backed_type_decorator(obj):
            autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
            return "postgresql.JSONB()"

    return False

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData
target_metadata = SQLModel.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _get_cli_command_name() -> str | None:
    command_options = config.cmd_opts
    if command_options is None:
        return None
    command = getattr(command_options, "cmd", (None,))[0]
    return getattr(command, "__name__", None)


def _should_run_without_database_connection() -> bool:
    command_name = _get_cli_command_name()
    command_options = config.cmd_opts
    if command_name == "revision":
        return not bool(getattr(command_options, "autogenerate", False))
    if command_name == "history":
        return not bool(getattr(command_options, "indicate_current", False))
    return command_name == "merge"


def compare_types(context: MigrationContext,
                  inspected_column: sa.Column,
                  metadata_column: sa.Column,
                  inspected_type: sa.sql.type_api.TypeEngine,
                  metadata_type: sa.sql.type_api.TypeEngine) -> bool | None:
    """Compare types of columns to determine if they are compatible."""

    if _is_json_backed_type_decorator(metadata_column.type) and isinstance(
        inspected_column.type, postgresql.JSONB
    ):
        return False

    # Default comparison for other types
    return None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=project_config.POSTGRES.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_types,
        render_item=render_item,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_without_database_connection() -> None:
    """Run revision-generation environments that do not need database state."""
    temporary_engine = sa.create_engine("sqlite://")
    try:
        with temporary_engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=compare_types,
                render_item=render_item,
                process_revision_directives=process_revision_directives,
                dont_mutate=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        temporary_engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_types,
            render_item=render_item,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
elif _should_run_without_database_connection():
    run_migrations_without_database_connection()
else:
    run_migrations_online()

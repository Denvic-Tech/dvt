from alembic import context

config = context.config
connection = config.attributes["connection"]
schema_name = config.attributes["extension_schema"]

context.configure(
    connection=connection,
    target_metadata=None,
    version_table="alembic_version",
    version_table_schema=schema_name,
    include_schemas=True,
)

with context.begin_transaction():
    context.run_migrations()

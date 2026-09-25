import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = importlib.import_module("migrations.versions.0062_canonical_extension_identity")


def _database(rows):
    engine = sa.create_engine("sqlite://")
    table = sa.Table(
        "extensions", sa.MetaData(),
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, unique=True),
        sa.Column("manifest_json", sa.JSON),
        sa.Column("state_json", sa.JSON),
        sa.Column("install_path", sa.String),
    )
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), rows)
    return engine


def test_upgrade_preserves_identity_state_and_physical_schema():
    engine = _database([{
        "id": "original-id", "name": "Bitrix24 Connector",
        "manifest_json": {"package_name": "bitrix24-connector", "version": "0.10.2"},
        "state_json": {"setting": 17}, "install_path": "/extensions/Bitrix24 Connector",
    }])
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        table = sa.Table("extensions", sa.MetaData(), autoload_with=connection)
        row = connection.execute(sa.select(table)).mappings().one()
        assert row["id"] == "original-id"
        assert row["name"] == "bitrix24-connector"
        assert row["state_json"] == {"setting": 17}
        assert row["install_path"] == "/extensions/Bitrix24 Connector"
        assert row["manifest_json"]["legacy_names"] == ["Bitrix24 Connector"]
        assert row["storage_schema"] == migration._storage_schema("Bitrix24 Connector")
        assert row["storage_schema"] != migration._storage_schema("bitrix24-connector")
    engine.dispose()


@pytest.mark.parametrize("second", [
    {"package_name": "bitrix24-connector"},
    {"package_name": "other-package", "legacy_names": ["Bitrix24 Connector"]},
])
def test_upgrade_rejects_ambiguous_records_before_changing_data(second):
    engine = _database([
        {"id": "a", "name": "Bitrix24 Connector",
         "manifest_json": {"package_name": "bitrix24-connector"}},
        {"id": "b", "name": "other-record", "manifest_json": second},
    ])
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(ValueError, match="Conflicting extension identity"):
                migration.upgrade()
        assert connection.execute(sa.text("SELECT name FROM extensions WHERE id='a'")).scalar() == "Bitrix24 Connector"
        assert "storage_schema" not in {c["name"] for c in sa.inspect(connection).get_columns("extensions")}
    engine.dispose()

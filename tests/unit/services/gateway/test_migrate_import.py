import importlib


def test_gateway_migrate_imports_without_circular_dependency() -> None:
    module = importlib.import_module("services.gateway.migrate")

    assert module.run_migrations is not None

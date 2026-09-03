from services.gateway.main import app


def test_db_catalog_openapi_exposes_paged_summary_and_targeted_detail_contracts():
    schema = app.openapi()
    paths = schema["paths"]

    assert "/db-connections/{connection_id}/catalog/databases" in paths
    assert "/db-connections/{connection_id}/catalog/schemas" in paths
    assert "/db-connections/{connection_id}/catalog/tables" in paths
    assert "/db-connections/{connection_id}/catalog/table" in paths
    assert "/db-connections/{connection_id}/catalog/table/preview" in paths
    assert "/db-connections/{connection_id}/catalog/refresh" in paths

    components = schema["components"]["schemas"]
    assert "columns" not in components["CatalogTableSummarySchema"]["properties"]
    assert "columns" in components["CatalogTableDetailsSchema"]["properties"]
    assert "next_cursor" in components["CatalogTablePageSchema"]["properties"]
    assert "total" not in components["CatalogTablePageSchema"]["properties"]
    preview = components["CatalogTablePreviewResponseSchema"]["properties"]
    assert set(preview) == {"columns", "rows", "truncated"}

    preview_operation = paths["/db-connections/{connection_id}/catalog/table/preview"]["get"]
    preview_parameters = {parameter["name"] for parameter in preview_operation["parameters"]}
    assert preview_parameters == {
        "connection_id",
        "table_name",
        "database_name",
        "schema_name",
    }


def test_db_catalog_list_limits_are_bounded_in_openapi():
    operation = app.openapi()["paths"]["/db-connections/{connection_id}/catalog/tables"]["get"]
    limit = next(parameter for parameter in operation["parameters"] if parameter["name"] == "limit")

    assert limit["schema"]["default"] == 100
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 200


def test_ddl_contract_uses_only_opaque_connection_id():
    schema = app.openapi()
    components = schema["components"]["schemas"]
    request_schemas = (
        "CreateDatabaseRequest",
        "CreateSchemaRequest",
        "GenerateSchemaDDLRequest",
        "CreateTableFromSchemaRequest",
        "CreateTableFromSQLRequest",
        "GenerateTableDDL",
        "ResolveWriteColumnsRequest",
        "ApplyTableColumnActionsRequest",
        "RecreateTableRequest",
        "TruncateTableRequest",
    )
    for name in request_schemas:
        request_schema = components[name]
        assert "connection_id" in request_schema["required"]
        assert "connection_id" in request_schema["properties"]
        assert "connection_metadata" not in request_schema["properties"]

    assert "DDLConnectionMetadata" not in components

    paths = schema["paths"]
    assert "/utils/ddl/create-database" in paths
    assert "/utils/ddl/create-schema" in paths
    assert "/utils/ddl/create-table" in paths
    assert "/utils/ddl/generate-table-ddl" in paths

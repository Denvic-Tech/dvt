from services.gateway.main import app


def test_data_catalog_openapi_exposes_search_details_and_usage():
    schema = app.openapi()
    paths = schema["paths"]

    assert "/data-catalog/datasets" in paths
    assert "/data-catalog/datasets/{dataset_id}" in paths
    assert "/data-catalog/datasets/{dataset_id}/usage" in paths

    components = schema["components"]["schemas"]
    assert "fields" not in components["DatasetSummarySchema"]["properties"]
    assert "fields" in components["DatasetDetailsSchema"]["properties"]
    assert set(components["DatasetSummarySchema"]["properties"]["freshness"]["enum"]) == {
        "fresh",
        "stale",
        "unverified",
        "unreachable",
        "not_found",
    }
    assert "next_cursor" in components["DatasetPageSchema"]["properties"]
    locator_properties = components["DatasetLocatorSchema"]["properties"]
    assert set(locator_properties) == {"kind", "location", "parts"}
    parameters = {parameter["name"] for parameter in paths["/data-catalog/datasets"]["get"]["parameters"]}
    assert "kind" in parameters and "dialect" not in parameters


def test_data_catalog_search_limit_is_bounded():
    operation = app.openapi()["paths"]["/data-catalog/datasets"]["get"]
    limit = next(parameter for parameter in operation["parameters"] if parameter["name"] == "limit")

    assert limit["schema"]["default"] == 50
    assert limit["schema"]["minimum"] == 1
    assert limit["schema"]["maximum"] == 200


def test_data_catalog_openapi_exposes_write_operations_and_provenance():
    schema = app.openapi()
    paths = schema["paths"]

    assert "patch" in paths["/data-catalog/datasets/{dataset_id}"]
    assert "post" in paths["/data-catalog/datasets/{dataset_id}/refresh"]
    assert "post" in paths["/data-catalog/datasets/{dataset_id}/fields/rename-confirm"]

    components = schema["components"]["schemas"]
    field_properties = components["DatasetFieldSchema"]["properties"]
    assert {"effective_description", "description_provenance", "description_updated_by"} <= set(field_properties)
    assert set(field_properties["description_provenance"]["enum"]) == {"declared", "source", "none"}
    assert "observed_at_run" in components["DatasetDetailsSchema"]["properties"]
    assert "description" in components["FieldDescriptionPatchSchema"]["required"]


def test_lineage_routes_and_schemas_are_exposed():
    schema = app.openapi()
    paths = schema["paths"]

    assert "/projects/{project_id}/lineage/nodes/{node_id}/fields" in paths
    assert "/projects/{project_id}/lineage/explain" in paths
    assert "/data-catalog/datasets/{dataset_id}/fields/{field_id}/dependents" in paths

    components = schema["components"]["schemas"]
    assert set(components["NodeFieldSchema"]["properties"]["op"]["enum"]) == {
        "source", "pass", "rename", "compute", "aggregate", "merge", "unknown",
    }
    assert set(components["NodeFieldSchema"]["properties"]["description_provenance"]["enum"]) == {
        "declared", "source", "inherited", "derived", "none", "unknown",
    }
    assert {"origin_field_name", "origin_location", "description_updated_by"} <= set(
        components["NodeFieldSchema"]["properties"]
    )
    assert "orphaned_annotations" in components["NodeFieldsResponseSchema"]["properties"]
    assert "patch" in paths["/projects/{project_id}/lineage/nodes/{node_id}/columns"]
    assert "get" in paths["/projects/{project_id}/lineage/columns"]
    assert set(components["ColumnGroupSchema"]["properties"]["kind"]["enum"]) == {"dataset_field", "node_column"}
    assert {"depth", "is_override", "description_provenance"} <= set(components["ColumnOccurrenceSchema"]["properties"])
    assert "lineage_available" in components["ProjectColumnsResponseSchema"]["required"]
    assert "rows" in components["ProjectColumnsResponseSchema"]["properties"]
    assert {"targets", "is_rename", "is_refinement", "depends_on"} <= set(components["ColumnRowSchema"]["properties"])
    assert set(components["DescriptionTargetSchema"]["properties"]["scope"]["enum"]) == {"project", "global"}
    assert "description" in components["ColumnDescriptionPatchSchema"]["required"]
    explain = paths["/projects/{project_id}/lineage/explain"]["get"]
    names = {parameter["name"] for parameter in explain["parameters"]}
    assert {"node_id", "column", "port", "direction", "max_depth", "X-Language"} <= names

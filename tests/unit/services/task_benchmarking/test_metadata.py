from services.task_benchmarking.metadata import metadata_metrics


def test_metadata_metrics_reports_utf8_bytes_and_catalog_object_counts():
    metadata = {
        "connection": {
            "databases": [
                {
                    "name": "аналитика",
                    "schemas": [
                        {
                            "name": "public",
                            "tables": [
                                {"name": "users", "columns": [{"name": "id"}, {"name": "email"}]}
                            ],
                        }
                    ],
                }
            ],
            "schemas": [],
            "tables": [],
        }
    }

    metrics = metadata_metrics(metadata)

    assert metrics["payload_bytes"] > 0
    assert metrics["databases"] == 1
    assert metrics["schemas"] == 1
    assert metrics["tables"] == 1
    assert metrics["columns"] == 2

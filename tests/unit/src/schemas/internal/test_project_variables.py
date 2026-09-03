from datetime import datetime, timedelta

from src.schemas.internal.project_variables import ProjectVariables


def test_project_variables_exposes_raw_values_for_runtime() -> None:
    project_variables = ProjectVariables(
        variables={
            "target_table": {"type": "STRING", "value": "warehouse.events"},
            "base_limit": {"type": "INT", "value": 10},
        }
    )

    assert project_variables.raw_values == {
        "target_table": "warehouse.events",
        "base_limit": 10,
    }


def test_project_variables_deserializes_datetime_and_timedelta_values() -> None:
    project_variables = ProjectVariables(
        variables={
            "run_at": {"type": "DATETIME", "value": "2026-04-27T10:15:00"},
            "window": {"type": "TIMEDELTA", "value": "PT2H15M"},
        }
    )

    assert project_variables.raw_values["run_at"] == datetime(2026, 4, 27, 10, 15, 0)
    assert project_variables.raw_values["window"] == timedelta(hours=2, minutes=15)
    assert project_variables.model_dump(mode="json") == {
        "variables": {
            "run_at": {
                "type": "DATETIME",
                "value": "2026-04-27T10:15:00",
                "is_list_type": False,
            },
            "window": {
                "type": "TIMEDELTA",
                "value": "PT2H15M",
                "is_list_type": False,
            },
        }
    }

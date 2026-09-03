import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import configure_mappers

from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
    ProjectScheduleRunRecord,
)
from src.modules.user.infra.db_models import UserRecord


def test_orchestrator_mapper_configuration_does_not_require_graph_models() -> None:
    project_root = Path(__file__).parents[4]
    env = os.environ | {"PYTHONPATH": str(project_root)}
    code = "\n".join(
        (
            "from sqlalchemy.orm import configure_mappers",
            "from src.modules.task_execution.infra.db_models import TaskRecord",
            "from src.modules.user.infra.db_models import UserRecord",
            "configure_mappers()",
        )
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_project_models_keep_foreign_keys_without_orm_relationships() -> None:
    assert UserRecord.__tablename__ == "users"
    configure_mappers()

    assert not inspect(ProjectRecord).relationships
    assert not inspect(ProjectScheduleRecord).relationships
    assert not inspect(ProjectScheduleRunRecord).relationships
    assert not inspect(ProjectFolderRecord).relationships

    assert ProjectRecord.__table__.c.user_id.foreign_keys
    assert ProjectRecord.__table__.c.organization_id.foreign_keys
    assert ProjectRecord.__table__.c.folder_id.foreign_keys
    assert ProjectScheduleRecord.__table__.c.project_id.foreign_keys
    assert ProjectScheduleRecord.__table__.c.scheduled_by_user_id.foreign_keys
    assert ProjectScheduleRunRecord.__table__.c.schedule_id.foreign_keys


def test_subgraph_keeps_organization_foreign_key_without_orm_relationship() -> None:
    from src.modules.pipeline_graph.infra.db_models import SubgraphRecord

    assert not inspect(SubgraphRecord).relationships
    assert SubgraphRecord.__table__.c.organization_id.foreign_keys

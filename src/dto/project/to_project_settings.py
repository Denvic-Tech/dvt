from src.modules.project.infra.db_models import ProjectRecord
from src.schemas.internal import ProjectSettings


def persistent_to_project_settings(persistent_project: ProjectRecord) -> ProjectSettings:
    return ProjectSettings.model_validate(persistent_project, from_attributes=True)

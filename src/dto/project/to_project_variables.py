from src.modules.project.infra.db_models import ProjectRecord
from src.schemas.internal import ProjectVariables


def persistent_to_project_variables(persistent_project: ProjectRecord) -> ProjectVariables:
    return ProjectVariables.model_validate(persistent_project, from_attributes=True)

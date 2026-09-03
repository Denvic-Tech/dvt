from typing import Annotated, get_args, get_origin, get_type_hints

from services.gateway.deps import project as project_deps
from services.gateway.routes.public.project import task as public_project_task


def test_public_create_task_uses_any_auth_project_dependency() -> None:
    project_annotation = get_type_hints(
        public_project_task.create_task,
        include_extras=True,
    )["project"]

    assert get_origin(project_annotation) is Annotated
    assert any(
        getattr(metadata, "dependency", None) is project_deps.get_user_project_by_path_any_auth
        for metadata in get_args(project_annotation)[1:]
    )

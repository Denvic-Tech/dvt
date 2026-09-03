from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session
from usrak.core.security import hash_password

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.db_connection.infra.connectors.dvt_service_files import DVTServiceFilesClient
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


def test_dvt_service_files_client_stores_reads_and_renames_files(test_db_engine) -> None:
    organization_id = f"org-{uuid4()}"
    project_id = f"project-{uuid4()}"
    user_id = f"user-{uuid4()}"
    with Session(test_db_engine) as session, session.begin():
        session.add(OrganizationRecord(id=organization_id, name="Test org"))
        session.flush()
        session.add(
            UserRecord(
                id=user_id,
                email=f"{user_id}@example.com",
                hashed_password=hash_password("Password123"),
                auth_provider="email",
                is_verified=True,
                is_active=True,
                role=DVTDefaultRoles.USER.value,
                organization_id=organization_id,
            )
        )
        session.flush()
        session.add(
            ProjectRecord(
                id=project_id,
                name="Test project",
                user_id=user_id,
                organization_id=organization_id,
            )
        )
    client = DVTServiceFilesClient(
        engine=test_db_engine,
        organization_id=organization_id,
        project_id=project_id,
        root_prefix="node-inputs/node-1/file",
    )

    client.upload_file(
        path="incoming",
        filename="data.csv",
        content=b"id,name\n1,Alice\n",
        content_type="text/csv",
    )

    assert client.download_file(path="incoming", filename="data.csv") == (
        "data.csv",
        b"id,name\n1,Alice\n",
        "text/csv",
    )
    assert client.listdir("incoming") == ["data.csv"]

    client.rename(src_path="incoming", dst_path="processed")

    assert not client.exists("incoming/data.csv")
    assert client.read_file("processed/data.csv") == b"id,name\n1,Alice\n"
    assert client.listdir("processed") == ["data.csv"]

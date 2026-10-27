from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import pytest

from src.modules.project_transfer.domain.entities import (
    BundleConnection,
    BundleFolder,
    BundleManifest,
    BundleProject,
    ColumnAnnotationSnapshot,
    GraphNodeSnapshot,
    GraphSnapshot,
    ProjectBundle,
    ProjectFile,
    ProjectMeta,
    RequiredNodeType,
    ScheduleSnapshot,
)
from src.modules.project_transfer.domain.exceptions import (
    BundleTooLargeError,
    InvalidBundleError,
    UnsupportedBundleFormatError,
)
from src.modules.project_transfer.domain.types import BUNDLE_FORMAT_VERSION
from src.modules.project_transfer.domain.value_objects import ConnectionBinding
from src.modules.project_transfer.infra.mappers import graph_from_doc
from src.modules.project_transfer.infra.schemas import GraphDoc
from src.modules.project_transfer.infra.serialization import read_bundle, write_bundle


def _bundle() -> ProjectBundle:
    return ProjectBundle(
        manifest=BundleManifest(
            format_version=BUNDLE_FORMAT_VERSION,
            dvt_version="1.2.3",
            exported_at=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
            source_instance_id="instance-1",
            options={"include_files": True},
            required_node_types=[RequiredNodeType(name="LoadCSV")],
            has_secrets=True,
        ),
        folders=[BundleFolder(ref="folder-1", name="Папка")],
        projects=[
            BundleProject(
                ref="project-1",
                folder_ref="folder-1",
                meta=ProjectMeta(name="Проект", store_enabled=True, ttl_time=10, workers_count=2),
                graph=GraphSnapshot(
                    nodes=[
                        GraphNodeSnapshot(
                            ui_id="n1",
                            type="custom",
                            position_x=1.5,
                            position_y=2.5,
                            name="LoadCSV",
                            display_name="CSV",
                            input_values={"path": {"__dvt_type": "const", "value": "data.csv"}},
                        )
                    ],
                    column_annotations=[
                        ColumnAnnotationSnapshot(node_ui_id="n1", port="output", column="amount", description="Сумма")
                    ],
                ),
                variables={"x": {"type": "int", "value": 1, "is_list_type": False}},
                files=[
                    ProjectFile(storage_path="node-inputs/n1/file", is_dir=True),
                    ProjectFile(
                        storage_path="node-inputs/n1/file/data.csv",
                        content=b"id\n1\n",
                        content_type="text/csv",
                        sha256="abc",
                    ),
                ],
                schedule=ScheduleSnapshot(cron="0 * * * *", mode="full"),
                connection_bindings=[
                    ConnectionBinding(node_ui_id="n1", input_name="connection_id", connection_ref="connection-1")
                ],
            )
        ],
        connections=[BundleConnection(ref="connection-1", name="pg", kind="sql", type="postgresql")],
        encrypted_secrets=b"DVTS-fake",
    )


def test_write_and_read_round_trip():
    stream = write_bundle(_bundle())

    with zipfile.ZipFile(stream) as archive:
        names = set(archive.namelist())
    assert names == {
        "manifest.json",
        "connections.json",
        "secrets.enc",
        "projects/project-1.json",
        "files/project-1/node-inputs/n1/file/data.csv",
    }
    stream.seek(0)

    restored = read_bundle(stream.read(), max_uncompressed_bytes=10_000_000)

    assert restored.manifest.dvt_version == "1.2.3"
    assert restored.manifest.has_secrets is True
    assert restored.encrypted_secrets == b"DVTS-fake"
    assert restored.folders[0].name == "Папка"
    project = restored.projects[0]
    assert project.meta.name == "Проект"
    assert project.variables == {"x": {"type": "int", "value": 1, "is_list_type": False}}
    assert project.graph.nodes[0].input_values == {"path": {"__dvt_type": "const", "value": "data.csv"}}
    assert [(a.node_ui_id, a.column, a.description, a.origin_key) for a in project.graph.column_annotations] == [
        ("n1", "amount", "Сумма", None)
    ]
    assert project.schedule.cron == "0 * * * *"
    assert project.connection_bindings[0].connection_ref == "connection-1"
    files = {file.storage_path: file for file in project.files}
    assert files["node-inputs/n1/file"].is_dir is True
    assert files["node-inputs/n1/file/data.csv"].content == b"id\n1\n"
    assert files["node-inputs/n1/file/data.csv"].size == 5
    assert restored.connections[0].type == "postgresql"


def test_graph_doc_without_annotations_section_is_read_as_empty():
    graph = graph_from_doc(GraphDoc.model_validate({"nodes": [], "edges": [], "subgraphs": []}))

    assert graph.column_annotations == []


def test_read_without_content_skips_file_payloads():
    stream = write_bundle(_bundle())

    restored = read_bundle(stream.read(), max_uncompressed_bytes=10_000_000, with_file_content=False)

    assert all(file.content is None for file in restored.projects[0].files)


def test_invalid_archives_are_rejected():
    with pytest.raises(InvalidBundleError):
        read_bundle(b"definitely not a zip", max_uncompressed_bytes=1_000)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", "{}")
    with pytest.raises(InvalidBundleError):
        read_bundle(buffer.getvalue(), max_uncompressed_bytes=1_000)

    stream = write_bundle(_bundle())
    with pytest.raises(BundleTooLargeError):
        read_bundle(stream.read(), max_uncompressed_bytes=10)


def test_unsupported_format_version():
    bundle = _bundle()
    bundle.manifest.format_version = BUNDLE_FORMAT_VERSION + 1

    with pytest.raises(UnsupportedBundleFormatError):
        read_bundle(write_bundle(bundle).read(), max_uncompressed_bytes=10_000_000)


def test_unsafe_entry_names_are_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.json", "{}")
    with pytest.raises(InvalidBundleError):
        read_bundle(buffer.getvalue(), max_uncompressed_bytes=1_000)

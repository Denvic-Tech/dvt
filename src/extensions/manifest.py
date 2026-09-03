from typing import Any

from src.types import ExtensionManifest


def build_manifest_stub(
    *,
    name: str,
    version: str = "",
    display_name: str | None = None,
    description: str = "",
    repository_url: str | None = None,
    homepage_url: str | None = None,
    dvt_version: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    backend: dict[str, Any] | None = None,
    frontend: dict[str, Any] | None = None,
    requirements: list[str] | None = None,
    state_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = ExtensionManifest(
        name=name,
        version=version,
        display_name=display_name,
        description=description,
        repository_url=repository_url,
        homepage_url=homepage_url,
        dvt_version=dvt_version,
        backend=backend or {},
        frontend=frontend,
        requirements=requirements or [],
        state_schema=state_schema or {},
        nodes=nodes or [],
    )
    return manifest.model_dump(mode="json", exclude_none=True)

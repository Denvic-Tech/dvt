from __future__ import annotations

from src.modules.extension_management.domain.entities import Extension
from src.modules.extension_management.domain.types import ExtensionDependencyStatus
from src.modules.extension_management.domain.value_objects import ExtensionPackagePreview
from src.modules.extension_management.infra.db_models import ExtensionRecord


def extension_record_to_domain(record: ExtensionRecord) -> Extension:
    return Extension(
        id=record.id,
        name=record.name,
        display_name=record.display_name,
        description=record.description,
        repository_url=record.repository_url,
        is_enabled=record.is_enabled,
        is_installed=record.is_installed,
        deps_status=ExtensionDependencyStatus(record.deps_status.value),
        current_version=record.current_version,
        last_version=record.last_version,
        install_path=record.install_path,
        manifest_json=dict(record.manifest_json or {}),
        state_json=dict(record.state_json or {}),
        available_versions=list(record.available_versions or []),
        error_message=record.error_message,
        installed_at=record.installed_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def package_preview_to_domain(preview) -> ExtensionPackagePreview:
    return ExtensionPackagePreview(
        package_id=preview.package_id,
        filename=preview.filename,
        name=preview.name,
        display_name=preview.display_name,
        version=preview.version,
        current_version=preview.current_version,
        dvt_version=preview.dvt_version,
        operation=preview.operation,
        compatible=preview.compatible,
        offline_ready=preview.offline_ready,
        has_wheelhouse=preview.has_wheelhouse,
        bundled_wheels_count=preview.bundled_wheels_count,
        warnings=tuple(preview.warnings or ()),
    )


__all__ = ["extension_record_to_domain", "package_preview_to_domain"]

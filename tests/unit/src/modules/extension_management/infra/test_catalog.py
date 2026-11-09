from dataclasses import asdict

from tests.fixtures.extension_catalog import release_payload

from src.modules.extension_management.infra.catalog import catalog_view
from src.schemas.http.extension import ExtensionCatalogVersionSchema

import config


def test_catalog_exposes_current_and_required_compatibility_values(monkeypatch) -> None:
    monkeypatch.setattr(config.APP, "VERSION", "1.22.0")
    compatible = release_payload("1.0.0")
    dvt_mismatch = release_payload("2.0.0", ">=1.24.0")
    platform_mismatch = release_payload("3.0.0")
    current_os = platform_mismatch["target"]["os"]
    required_os = "linux" if current_os != "linux" else "windows"
    platform_mismatch["target"]["os"] = required_os

    versions, recommended = catalog_view([compatible, dvt_mismatch, platform_mismatch], None)
    schema_by_version = {
        release.version: ExtensionCatalogVersionSchema(**asdict(release)).model_dump()
        for release in versions
    }

    assert recommended == "1.0.0"
    assert schema_by_version["1.0.0"]["incompatibility_details"] == []
    assert schema_by_version["2.0.0"]["incompatibility_details"] == [
        {"field": "dvt_version", "current": "1.22.0", "required": ">=1.24.0"}
    ]
    assert schema_by_version["3.0.0"]["incompatibility_details"] == [
        {"field": "os", "current": current_os, "required": required_os}
    ]

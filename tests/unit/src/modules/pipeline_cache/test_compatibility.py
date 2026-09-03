from __future__ import annotations

import tomllib
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

from src.modules.pipeline_cache.domain.fingerprints import (
    _application_runtime_identity,
    create_dask_partition_fingerprint,
    create_node_inputs_fingerprint,
    create_node_output_fingerprint,
    create_node_runtime_fingerprint,
)
from src.modules.pipeline_cache.domain.keys import PDFKey, index_key_from_str
from src.modules.pipeline_cache.infra.fingerprints import create_sa_engine_fingerprint


class _FakeNode:
    pass


def test_pipeline_cache_module_has_no_direct_config_or_legacy_imports() -> None:
    module_root = Path("src/modules/pipeline_cache")
    for path in module_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import config" not in text, path
        assert "from config import" not in text, path
        assert "src.caching" not in text, path
        assert "src.managers.cache_manager" not in text, path
        assert "src.managers.index_manager" not in text, path

    assert not (module_root / "flow" / "repositories").exists()
    assert not (module_root / "flow" / "gateways").exists()

    forbidden_domain_flow_imports = (
        "import sqlalchemy",
        "from sqlalchemy",
        "import pydantic",
        "from pydantic",
        "import sqlmodel",
        "from sqlmodel",
        "import fastapi",
        "from fastapi",
        "src.models",
        "src.schemas",
        "src.dto",
        "src.crud",
        "src.clients",
        "src.db",
        "..infra",
    )
    for layer in (module_root / "domain", module_root / "flow"):
        for path in layer.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for forbidden in forbidden_domain_flow_imports:
                assert forbidden not in text, (path, forbidden)


def test_fingerprint_builders_are_stable_and_prefixed() -> None:
    parent_hashes = {"source.output": "abc123"}
    constant_inputs = {"limit": 10, "enabled": True}
    pdf = pd.DataFrame({"value": [1, 2], "tag": ["a", "b"]})
    engine = sa.create_engine("sqlite://")

    assert create_node_inputs_fingerprint(_FakeNode, parent_hashes, constant_inputs).startswith("inputs:")
    assert create_node_output_fingerprint("proj", "node", "output") == "node_output:proj:node:output"
    assert create_dask_partition_fingerprint(
        pdf,
        expr_name="expr-name",
        node_name="MyNode",
        part_no=1,
        npartitions=3,
    ).startswith("dd_part:2/3:MyNode:")
    changed_pdf = pdf.copy()
    changed_pdf.loc[0, "value"] = 999
    assert create_dask_partition_fingerprint(
        pdf,
        expr_name="expr-name",
        node_name="MyNode",
        part_no=1,
        npartitions=3,
    ) != create_dask_partition_fingerprint(
        changed_pdf,
        expr_name="expr-name",
        node_name="MyNode",
        part_no=1,
        npartitions=3,
    )
    assert create_sa_engine_fingerprint(engine).startswith("sa_engine:")


def test_index_key_roundtrip_works() -> None:
    key = PDFKey(project_id="proj-1", node_id="node-1", output_name="out", part_no=2)
    serialized = key.to_str(sep=":::", ensure_full=True)

    assert index_key_from_str(PDFKey, serialized, sep=":::") == key


def test_runtime_fingerprint_includes_stable_application_build_identity(monkeypatch) -> None:
    monkeypatch.setenv("DVT_BUILD_ID", "build-a")
    create_node_runtime_fingerprint.cache_clear()
    build_a = create_node_runtime_fingerprint(_FakeNode)

    monkeypatch.setenv("DVT_BUILD_ID", "build-b")
    create_node_runtime_fingerprint.cache_clear()
    build_b = create_node_runtime_fingerprint(_FakeNode)

    assert build_a != build_b


def test_runtime_identity_falls_back_to_pyproject_version(monkeypatch) -> None:
    monkeypatch.delenv("DVT_BUILD_ID", raising=False)
    monkeypatch.delenv("DVT_VERSION", raising=False)
    with Path("pyproject.toml").open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]

    assert _application_runtime_identity() == f"version:{project_version}"

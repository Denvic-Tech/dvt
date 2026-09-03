from __future__ import annotations

import inspect
import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import dask.dataframe as dd
import pandas as pd

from core.hashing import get_hash


@dataclass(frozen=True, slots=True)
class KeyParams:
    include_parent_hashes: bool
    include_constant_inputs: bool
    prefix: str


PARAMS_MAP = {
    pd.DataFrame: KeyParams(
        include_parent_hashes=True,
        include_constant_inputs=True,
        prefix="pd_df",
    ),
    dd.DataFrame: KeyParams(
        include_parent_hashes=True,
        include_constant_inputs=True,
        prefix="dd_df",
    ),
}


def _application_runtime_identity() -> str:
    build_id = os.getenv("DVT_BUILD_ID", "").strip()
    if build_id:
        return f"build:{build_id}"

    runtime_version = os.getenv("DVT_VERSION", "").strip()
    if runtime_version:
        return f"version:{runtime_version}"

    pyproject_path = Path(__file__).resolve().parents[4] / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as file:
            project_version = str(tomllib.load(file).get("project", {}).get("version", "")).strip()
    except (OSError, tomllib.TOMLDecodeError):
        project_version = ""
    return f"version:{project_version or 'unknown'}"


def create_node_inputs_fingerprint(
    node_class: type[Any],
    parent_hashes: dict[str, str] | None = None,
    constant_inputs: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {"node_name": node_class.__name__}
    if parent_hashes:
        payload["parent_hashes"] = sorted(parent_hashes.items())
    if constant_inputs:
        payload["constant_inputs"] = sorted(constant_inputs.items())
    return f"inputs:{get_hash(payload, deep=False).hex()}"


def create_node_output_fingerprint(project_id: str, node_id: str, output_name: str) -> str:
    return f"node_output:{project_id}:{node_id}:{output_name}"


@lru_cache(maxsize=1024)
def create_node_runtime_fingerprint(node_class: type[Any]) -> str:
    """Cheap implementation identity; never materializes dataframe inputs."""
    try:
        implementation = inspect.getsource(node_class)
    except (OSError, TypeError):
        try:
            implementation = inspect.getsource(node_class.process)
        except (OSError, TypeError, AttributeError):
            implementation = ""
    payload = {
        "module": node_class.__module__,
        "qualname": node_class.__qualname__,
        "implementation": implementation,
        "extension_name": getattr(node_class, "EXTENSION_NAME", None),
        "extension_version": getattr(node_class, "EXTENSION_VERSION", None),
        "application_runtime": _application_runtime_identity(),
    }
    return f"node_runtime:{get_hash(payload, deep=False).hex()}"


def create_dataframe_schema_fingerprint(meta: pd.DataFrame) -> str:
    return f"df_schema:{get_hash(meta, deep=False).hex()}"


def create_dask_partition_fingerprint(
    pdf: pd.DataFrame,
    *,
    expr_name: str,
    node_name: str,
    part_no: int,
    npartitions: int,
) -> str:
    """Compatibility content checksum; not used by generation-scoped execution cache keys."""
    payload = {
        "obj": pdf,
        "expr_name": expr_name,
    }
    return f"dd_part:{part_no + 1}/{npartitions}:{node_name}:{get_hash(payload, deep=True).hex()}"

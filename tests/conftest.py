from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

os.environ["LOG_TO_DB"] = "false"

from .fixtures.df import (
    simple_df,
    simple_ddf,
    simple_df_two,
    types_test_dataframe,
)

import pytest

_PYTEST_TMP_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "pytest"
_PYTEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)

_TEMP_ROOT = _PYTEST_TMP_ROOT / f"debug-root-{os.getpid()}"
_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEMP_ROOT))

_SYSTEM_TMP_ROOT = _PYTEST_TMP_ROOT / "system-temp"
_SYSTEM_TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["TMPDIR"] = str(_SYSTEM_TMP_ROOT)
os.environ["TEMP"] = str(_SYSTEM_TMP_ROOT)
os.environ["TMP"] = str(_SYSTEM_TMP_ROOT)
tempfile.tempdir = str(_SYSTEM_TMP_ROOT)

_CUSTOM_TMP_ROOT = _PYTEST_TMP_ROOT / "custom"
_CUSTOM_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path() -> Generator[Path, Any, None]:
    """Local tmp_path replacement to avoid permission issues in pytest temp roots."""
    path = _CUSTOM_TMP_ROOT / f"tmp{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

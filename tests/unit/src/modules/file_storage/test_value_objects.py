import pytest

from src.modules.file_storage.domain.exceptions import (
    InvalidStorageEntryNameError,
    InvalidStoragePathError,
)
from src.modules.file_storage.domain.value_objects import (
    StorageEntryName,
    StorageRelativePath,
)


def test_storage_relative_path_normalizes_slashes_and_segments() -> None:
    path = StorageRelativePath.from_raw(r"/reports\2025/./april/")

    assert path.value == "reports/2025/april"


def test_storage_relative_path_rejects_parent_traversal() -> None:
    with pytest.raises(InvalidStoragePathError):
        StorageRelativePath.from_raw("../secret")


def test_storage_entry_name_rejects_path_separator() -> None:
    with pytest.raises(InvalidStorageEntryNameError):
        StorageEntryName.from_raw("folder/file.txt")


def test_storage_relative_path_supports_rename_and_move() -> None:
    path = StorageRelativePath.from_raw("reports/2025/april.csv")

    assert path.with_name("may.csv").value == "reports/2025/may.csv"
    assert path.move_to("archive/2025").value == "archive/2025/april.csv"


def test_storage_relative_path_rejects_rename_of_root() -> None:
    with pytest.raises(InvalidStoragePathError):
        StorageRelativePath.from_raw("").with_name("archive")

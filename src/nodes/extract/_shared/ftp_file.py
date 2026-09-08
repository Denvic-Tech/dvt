from __future__ import annotations

import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

import fsspec


def _temp_suffix(path: str, default: str = "") -> str:
    return Path(urlparse(path).path).suffix or default


@contextmanager
def localized_ftp_file(
    path: str,
    storage_options: Mapping[str, object],
    *,
    prefix: str,
    default_suffix: str = "",
) -> Iterator[str]:
    """Download one FTP file through a fresh session and remove the local copy afterwards."""
    with tempfile.NamedTemporaryFile(
        delete=False,
        prefix=prefix,
        suffix=_temp_suffix(path, default_suffix),
    ) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        ftp_fs = fsspec.filesystem("ftp", **dict(storage_options))
        remote_path = ftp_fs._strip_protocol(path)
        ftp_fs.get_file(remote_path, str(temp_path))
        yield str(temp_path)
    finally:
        with suppress(FileNotFoundError):
            temp_path.unlink()

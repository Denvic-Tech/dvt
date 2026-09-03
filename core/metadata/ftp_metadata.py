from __future__ import annotations

from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

from cachetools import TTLCache, cached

from core.types import FTPDirectoryMetadata, FTPFile, FTPFolder, FTPMetadata, FTPNode

if TYPE_CHECKING:  # pragma: no cover
    from ftplib import FTP, FTP_TLS
else:
    FTP = Any
    FTP_TLS = Any

try:
    from ftplib import FTP, FTP_TLS
except ImportError:  # pragma: no cover
    FTP = None
    FTP_TLS = None


FTP_MODE = "ftp"
FTPS_IMPLICIT_MODE = "ftps_implicit"
FTPS_EXPLICIT_MODE = "ftps_explicit"

ftp_metadata_cache = TTLCache(maxsize=100, ttl=2)
ftp_path_metadata_cache = TTLCache(maxsize=500, ttl=2)


def _make_connection_string(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
) -> str:
    user_part = ""
    if username:
        pass_hint = f":{password[:4]}***" if password else ""
        user_part = f"{username}{pass_hint}@"
    return f"ftp://{user_part}{host}:{port}"


def _get_effective_username(username: str | None, anonymous: bool) -> str:
    if anonymous:
        return "anonymous"
    return username or ""


def _get_effective_password(password: str | None, anonymous: bool) -> str:
    if anonymous:
        return ""
    return password or ""


def _get_ssl_context_params(
    certfile: str | None,
    keyfile: str | None,
) -> dict[str, Any]:
    ssl_kwargs: dict[str, Any] = {}
    if certfile:
        ssl_kwargs["certfile"] = certfile
    if keyfile:
        ssl_kwargs["keyfile"] = keyfile
    return ssl_kwargs


def _create_ftp_client(
    host: str,
    port: int,
    mode: str = FTP_MODE,
    username: str | None = None,
    password: str | None = None,
    anonymous: bool = False,
    encoding: str = "utf-8",
    initial_directory: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
):
    if FTP is None:
        raise RuntimeError("FTP support requires Python's ftplib module")

    timeout = 30
    if mode in (FTPS_IMPLICIT_MODE, FTPS_EXPLICIT_MODE):
        client = FTP_TLS(
            timeout=timeout,
            encoding=encoding,
            **_get_ssl_context_params(certfile=certfile, keyfile=keyfile),
        )
    else:
        client = FTP(timeout=timeout, encoding=encoding)

    client.connect(host, port)

    if hasattr(client, "prot_p"):
        client.auth()
        client.prot_p()

    client.login(
        user=_get_effective_username(username=username, anonymous=anonymous),
        passwd=_get_effective_password(password=password, anonymous=anonymous),
    )
    client.set_pasv(True)

    if initial_directory:
        with suppress(Exception):
            client.cwd(initial_directory)

    return client


def _close_ftp_client(client) -> None:
    try:
        client.quit()
    except Exception:
        with suppress(Exception):
            client.close()


@contextmanager
def _build_ftp_client(**kwargs):
    client = _create_ftp_client(**kwargs)
    try:
        yield client
    finally:
        _close_ftp_client(client)


def _normalize_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


@cached(cache=ftp_metadata_cache)
def load_ftp_metadata(
    connection_id: str,
    host: str,
    port: int,
    mode: str = FTP_MODE,
    username: str | None = None,
    password: str | None = None,
    anonymous: bool = False,
    encoding: str = "utf-8",
    initial_directory: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    max_items: int = 100,
) -> FTPMetadata:
    initial_path = initial_directory or "/"
    nodes, _, _ = load_ftp_path_metadata(
        host=host,
        port=port,
        mode=mode,
        username=username,
        password=password,
        anonymous=anonymous,
        encoding=encoding,
        initial_directory=initial_directory,
        certfile=certfile,
        keyfile=keyfile,
        path=initial_path,
        max_items=max_items,
    )

    total_size = sum(node.size for node in nodes if isinstance(node, FTPFile))
    files_count = sum(1 for node in nodes if isinstance(node, FTPFile))
    folders_count = sum(1 for node in nodes if isinstance(node, FTPFolder))

    directory_metadata = FTPDirectoryMetadata(
        host=host,
        current_path=initial_path,
        nodes=nodes,
        total_size=total_size,
        files_count=files_count,
        folders_count=folders_count,
    )

    conn_str = _make_connection_string(
        host=host,
        port=port,
        username=None if anonymous else username,
        password=None if anonymous else password,
    )

    return FTPMetadata(
        connection_id=connection_id,
        connection_string=conn_str,
        host=host,
        port=port,
        mode=mode or FTP_MODE,
        username=None if anonymous else username,
        anonymous=anonymous,
        initial_directory=initial_path,
        encoding=encoding or "utf-8",
        directory=directory_metadata,
    )


@cached(cache=ftp_path_metadata_cache)
def load_ftp_path_metadata(
    host: str,
    port: int,
    mode: str = FTP_MODE,
    username: str | None = None,
    password: str | None = None,
    anonymous: bool = False,
    encoding: str = "utf-8",
    initial_directory: str | None = None,
    certfile: str | None = None,
    keyfile: str | None = None,
    path: str = "/",
    max_items: int = 1000,
) -> tuple[list[FTPNode], bool, str | None]:
    nodes: list[FTPNode] = []
    current_path = _normalize_path(path)

    try:
        with _build_ftp_client(
            host=host,
            port=port,
            mode=mode,
            username=username,
            password=password,
            anonymous=anonymous,
            encoding=encoding,
            initial_directory=initial_directory,
            certfile=certfile,
            keyfile=keyfile,
        ) as ftp_client:
            entries = list(ftp_client.mlsd(current_path))
    except Exception:
        return [], False, None

    for name, facts in entries[:max_items]:
        if name in (".", ".."):
            continue

        item_path = f"{current_path.rstrip('/')}/{name}"
        perms = facts.get("unix.mode") or facts.get("perm")

        if facts.get("type") == "dir":
            nodes.append(
                FTPFolder(
                    name=name,
                    path=item_path,
                    permissions=perms,
                )
            )
        else:
            nodes.append(
                FTPFile(
                    name=name,
                    path=item_path,
                    size=int(facts.get("size", 0)),
                    last_modified=None,
                    permissions=perms,
                )
            )

    is_truncated = len(entries) > max_items
    return nodes, is_truncated, None

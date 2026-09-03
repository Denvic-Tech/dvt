from typing import TYPE_CHECKING, Any

from cachetools import TTLCache, cached

from core.types import S3Bucket, S3File, S3Folder, S3Metadata, S3Node

if TYPE_CHECKING:
    import boto3
    from botocore.config import Config
else:
    boto3 = Any
    Config = Any

try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None
    Config = None

s3_metadata_cache = TTLCache(maxsize=100, ttl=2)  # 5 минут кэш
s3_path_metadata_cache = TTLCache(maxsize=500, ttl=2)  # 1 минута кэш для путей


def _make_connection_string(
    endpoint_url: str | None, region: str | None, access_key_id: str | None = None
) -> str:
    """
    Создать строку подключения для S3 (без секретного ключа).
    """
    parts = ["s3://"]

    if access_key_id:
        parts.append(f"access_key={access_key_id[:4]}***")

    if endpoint_url:
        parts.append(f"@endpoint={endpoint_url}")

    if region:
        parts.append(f"@region={region}")

    return "".join(parts) if len(parts) > 1 else "s3://<unknown>"


def _build_client_kwargs(
    access_token_id: str,
    access_token_key: str,
    region_name: str | None = None,
    endpoint_url: str | None = None,
    session_token: str | None = None,
    use_ssl: bool = True,
    verify: bool = False,
):
    client_kwargs: dict[str, Any] = {
        "region_name": region_name,
        "endpoint_url": endpoint_url,
        "aws_access_key_id": access_token_id,
        "aws_secret_access_key": access_token_key,
        "aws_session_token": session_token,
        "use_ssl": use_ssl,
        "verify": verify,
    }
    return {k: v for k, v in client_kwargs.items() if v is not None}


def _build_botocore_config(
    signature_version: str | None = None,
    path_style: bool = False,
) -> Config | None:
    config_kwargs: dict[str, Any] = {}
    if signature_version:
        config_kwargs["signature_version"] = signature_version
    if path_style:
        config_kwargs.setdefault("s3", {})["addressing_style"] = "path"

    if not config_kwargs:
        return None

    return Config(**config_kwargs)


def _build_s3_client(
    access_token_id: str,
    access_token_key: str,
    region_name: str | None = None,
    endpoint_url: str | None = None,
    session_token: str | None = None,
    use_ssl: bool = True,
    verify: bool = False,
    signature_version: str | None = None,
    path_style: bool = False,
):
    if boto3 is None:
        raise RuntimeError("S3 support requires boto3 and botocore lib")

    s3_client_kwargs = _build_client_kwargs(
        access_token_id=access_token_id,
        access_token_key=access_token_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
        session_token=session_token,
        use_ssl=use_ssl,
        verify=verify,
    )
    botocore_config = _build_botocore_config(
        signature_version=signature_version,
        path_style=path_style,
    )

    if botocore_config is not None:
        s3_client_kwargs["config"] = botocore_config

    return boto3.client("s3", **s3_client_kwargs)


@cached(cache=s3_metadata_cache)
def load_s3_metadata(
    bucket: str,
    access_token_id: str,
    access_token_key: str,
    connection_id: str,
    region_name: str | None = None,
    endpoint_url: str | None = None,
    prefix: str | None = None,
    session_token: str | None = None,
    use_ssl: bool = True,
    verify: bool = False,
    signature_version: str | None = None,
    path_style: bool = False,
    max_objects_per_bucket: int = 100,
) -> S3Metadata:
    """
    Загружает метаданные S3 подключения только для заданного бакета.
    """
    s3_client = _build_s3_client(
        access_token_id=access_token_id,
        access_token_key=access_token_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
        session_token=session_token,
        use_ssl=use_ssl,
        verify=verify,
        signature_version=signature_version,
        path_style=path_style,
    )

    nodes: list[S3Node] = []
    total_size = 0
    files_count = 0
    folders_count = 0

    list_params = {
        "Bucket": bucket,
        "Delimiter": "/",
        "MaxKeys": max_objects_per_bucket,
    }

    if prefix:
        list_params["Prefix"] = prefix

    response_page = s3_client.list_objects_v2(**list_params)

    for prefix_info in response_page.get("CommonPrefixes", []):
        folder_prefix: str = prefix_info["Prefix"]

        trimmed = folder_prefix.rstrip("/")
        name = trimmed.split("/")[-1] if trimmed else ""

        if name:
            folder = S3Folder(name=name, path=folder_prefix)
            nodes.append(folder)
            folders_count += 1

    for obj in response_page.get("Contents", []):
        key: str = obj["Key"]

        if key.endswith("/"):
            continue

        name = key.split("/")[-1]

        if name:
            s3_file = S3File(
                name=name,
                path=key,
                size=obj["Size"],
                last_modified=obj.get("LastModified"),
                etag=obj.get("ETag"),
                storage_class=obj.get("StorageClass"),
            )
            nodes.append(s3_file)
            total_size += obj["Size"]
            files_count += 1

    connection_string = _make_connection_string(endpoint_url, region_name, access_token_id)

    return S3Metadata(
        bucket=S3Bucket(
            name=bucket,
            creation_date=None,
            nodes=nodes,
            total_size=total_size,
            files_count=files_count,
            folders_count=folders_count,
        ),
        endpoint_url=endpoint_url,
        region=region_name,
        connection_string=connection_string,
        connection_id=connection_id,
        connection_prefix=prefix,
    )


@cached(cache=s3_path_metadata_cache)
def load_s3_path_metadata(
    bucket: str,
    access_token_id: str,
    access_token_key: str,
    path: str = "",
    region_name: str | None = None,
    endpoint_url: str | None = None,
    prefix: str | None = None,
    session_token: str | None = None,
    use_ssl: bool = True,
    verify: bool = False,
    signature_version: str | None = None,
    path_style: bool = False,
    max_items: int = 1000,
) -> tuple[list[S3Node], bool, str | None]:
    """
    Загружает метаданные конкретного пути в S3 бакете.
    """

    s3_client = _build_s3_client(
        access_token_id=access_token_id,
        access_token_key=access_token_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
        session_token=session_token,
        use_ssl=use_ssl,
        verify=verify,
        signature_version=signature_version,
        path_style=path_style,
    )
    nodes: list[S3Node] = []
    is_truncated = False
    next_token = None

    path = path.strip("/")
    base_prefix = prefix.strip("/") if prefix else ""
    if base_prefix:
        full_prefix = f"{base_prefix}/{path}/" if path else f"{base_prefix}/"
    else:
        full_prefix = f"{path}/" if path else ""

    # Получаем список узлов в конкретном пути с использованием delimiter
    list_params = {
        "Bucket": bucket,
        "Delimiter": "/",
        "MaxKeys": max_items,
    }

    if full_prefix:
        list_params["Prefix"] = full_prefix

    response = s3_client.list_objects_v2(**list_params)

    # Обрабатываем папки (CommonPrefixes)
    for prefix_info in response.get("CommonPrefixes", []):
        prefix_key: str = prefix_info["Prefix"]

        # Извлекаем имя папки (последний сегмент пути без "/")
        trimmed = prefix_key.rstrip("/")
        name = trimmed.split("/")[-1] if trimmed else ""

        # Вычисляем относительный путь (без base prefix)
        relative_path = prefix_key
        if base_prefix:
            base_with_slash = f"{base_prefix}/"
            if relative_path.startswith(base_with_slash):
                relative_path = relative_path[len(base_with_slash) :]

        if name:  # Игнорируем пустые имена
            folder = S3Folder(
                name=name,
                path=relative_path.rstrip("/"),  # Путь без завершающего слеша
            )
            nodes.append(folder)

    # Обрабатываем файлы (Contents)
    for obj in response.get("Contents", []):
        key: str = obj["Key"]

        # Пропускаем "папки" (ключи, заканчивающиеся на "/")
        if key.endswith("/"):
            continue

        # Вычисляем относительный путь (без base prefix)
        relative_path = key
        if base_prefix:
            base_with_slash = f"{base_prefix}/"
            if relative_path.startswith(base_with_slash):
                relative_path = relative_path[len(base_with_slash) :]

        # Извлекаем имя файла (последний сегмент пути)
        name = relative_path.split("/")[-1]

        if name:  # Игнорируем пустые имена
            s3_file = S3File(
                name=name,
                path=relative_path,
                size=obj["Size"],
                last_modified=obj.get("LastModified"),
                etag=obj.get("ETag"),
                storage_class=obj.get("StorageClass"),
            )
            nodes.append(s3_file)

    is_truncated = response.get("IsTruncated", False)
    next_token = response.get("NextContinuationToken")

    return nodes, is_truncated, next_token

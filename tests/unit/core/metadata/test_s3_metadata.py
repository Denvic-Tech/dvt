from datetime import datetime

from core.metadata import s3_metadata
from core.metadata.s3_metadata import (
    _make_connection_string,
    load_s3_metadata,
    load_s3_path_metadata,
)


def test_make_connection_string_masks_access_key():
    conn_str = _make_connection_string("https://s3.local", "ru", "AKIA123456")
    assert conn_str.startswith("s3://access_key=AKIA***")
    assert "@endpoint=https://s3.local" in conn_str
    assert "@region=ru" in conn_str


def test_load_s3_metadata_basic(monkeypatch):
    s3_metadata.s3_metadata_cache.clear()
    captured_client_kwargs = {}

    class FakeClient:
        def list_objects_v2(self, **kwargs):
            assert kwargs["Bucket"] == "bucket"
            assert kwargs["Prefix"] == "base"
            return {
                "CommonPrefixes": [{"Prefix": "base/folder/"}],
                "Contents": [
                    {
                        "Key": "base/file.csv",
                        "Size": 10,
                        "LastModified": datetime(2024, 1, 1),
                        "ETag": "etag",
                        "StorageClass": "STANDARD",
                    }
                ],
            }

    def _fake_build_s3_client(**kwargs):
        captured_client_kwargs.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(s3_metadata, "_build_s3_client", _fake_build_s3_client)

    meta = load_s3_metadata(
        bucket="bucket",
        region_name="ru-central1",
        endpoint_url="https://s3.local",
        access_token_id="AKIA1234",
        access_token_key="secret",
        session_token=None,
        use_ssl=False,
        path_style=True,
        signature_version=None,
        prefix="base",
        connection_id="conn-1",
        verify=False,
        max_objects_per_bucket=100,
    )

    assert captured_client_kwargs["endpoint_url"] == "https://s3.local"
    assert captured_client_kwargs["region_name"] == "ru-central1"
    assert captured_client_kwargs["path_style"] is True
    assert captured_client_kwargs["use_ssl"] is False
    assert meta.bucket.name == "bucket"
    assert meta.bucket.files_count == 1
    assert meta.bucket.folders_count == 1
    assert meta.bucket.total_size == 10
    assert meta.connection_prefix == "base"


def test_load_s3_path_metadata_prefix(monkeypatch):
    s3_metadata.s3_path_metadata_cache.clear()

    class FakeClient:
        def list_objects_v2(self, **kwargs):
            assert kwargs["Prefix"] == "base/sub/"
            return {
                "CommonPrefixes": [{"Prefix": "base/sub/folder/"}],
                "Contents": [
                    {"Key": "base/sub/file.txt", "Size": 5},
                ],
                "IsTruncated": False,
            }

    monkeypatch.setattr(s3_metadata, "_build_s3_client", lambda **_: FakeClient())

    nodes, is_truncated, next_token = load_s3_path_metadata(
        bucket="bucket",
        region_name="ru-central1",
        endpoint_url="https://s3.local",
        access_token_id="AKIA1234",
        access_token_key="secret",
        session_token=None,
        use_ssl=False,
        path_style=True,
        signature_version=None,
        prefix="base",
        max_items=1000,
        verify=False,
        path="sub",
    )

    assert is_truncated is False
    assert next_token is None

    names = {node.name for node in nodes}
    paths = {node.path for node in nodes}

    assert "folder" in names
    assert "file.txt" in names
    assert "sub/folder" in paths
    assert "sub/file.txt" in paths

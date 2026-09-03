from __future__ import annotations

from datetime import UTC, datetime

from src.modules.file_storage.flow.connections import ResolvedS3StorageConnection
from src.modules.file_storage.infra.clients import S3StorageClient
from src.modules.file_storage.infra.gateways.s3 import S3FileStorageGateway


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "CommonPrefixes": [{"Prefix": "incoming/reports/2026/"}],
            "Contents": [
                {
                    "Key": "incoming/reports/summary.csv",
                    "Size": 12,
                    "LastModified": datetime(2026, 6, 1, tzinfo=UTC),
                    "ETag": '"etag"',
                    "StorageClass": "STANDARD",
                }
            ],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        }


def test_s3_gateway_list_nodes_uses_bound_prefix_and_returns_relative_paths() -> None:
    client = _FakeS3Client()
    gateway = S3FileStorageGateway(
        ResolvedS3StorageConnection(
            client=S3StorageClient(client=client),
            bucket="analytics",
            prefix="incoming",
        )
    )

    tree = gateway.list_nodes(path="reports", max_items=25)

    assert client.calls == [
        {
            "Bucket": "analytics",
            "Delimiter": "/",
            "MaxKeys": 25,
            "Prefix": "incoming/reports/",
        }
    ]
    assert tree.path == "reports"
    assert tree.is_truncated is True
    assert tree.next_token == "next-page"
    assert [node.name for node in tree.nodes] == ["2026", "summary.csv"]
    assert [node.path for node in tree.nodes] == ["reports/2026", "reports/summary.csv"]

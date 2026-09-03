from unittest.mock import Mock

from src.modules.file_storage.infra.clients import s3 as s3_module
from src.modules.file_storage.infra.clients.s3 import S3StorageClient


def test_s3_storage_client_forwards_disabled_certificate_verification(monkeypatch) -> None:
    boto_client = Mock()
    create_client = Mock(return_value=boto_client)
    monkeypatch.setattr(s3_module.boto3, "client", create_client)

    client = S3StorageClient(
        endpoint_url="https://minio.example.test",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        region_name="us-east-1",
        use_ssl=True,
        verify=False,
    )

    assert client.client is boto_client
    create_client.assert_called_once_with(
        "s3",
        endpoint_url="https://minio.example.test",
        aws_access_key_id="access-key",
        aws_secret_access_key="secret-key",
        region_name="us-east-1",
        use_ssl=True,
        verify=False,
    )

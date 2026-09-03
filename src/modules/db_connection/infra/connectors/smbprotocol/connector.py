from __future__ import annotations

from db_connection import ConnectionCheckResult, Connector, InfrastructureError, ValidatedConnection

from .client import SMBProtocolClient
from .schemas import SMBProtocolProperties, SMBProtocolSecrets

try:
    from smbprotocol.exceptions import (
        LogonFailure,
        SMBAuthenticationError,
        SMBException,
        SMBOSError,
    )
except ImportError:  # pragma: no cover
    SMBAuthenticationError = LogonFailure = SMBException = SMBOSError = Exception


class SMBProtocolConnector(Connector):
    async def check(self, connection: ValidatedConnection) -> ConnectionCheckResult:
        client = None
        try:
            client = await self.get_client(connection)
            entries = client.listdir()
            return ConnectionCheckResult(
                name=connection.name,
                connected=True,
                message=f"Connected to {client.root_path}. Entries: {len(entries)}.",
            )
        except (SMBAuthenticationError, LogonFailure) as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="SMB authentication failed.",
                exception=str(exc),
            )
        except TimeoutError:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message="SMB connection timed out.",
            )
        except (OSError, SMBOSError, SMBException) as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message=f"SMB connection failed: {exc!s}",
                exception=str(exc),
            )
        except Exception as exc:
            return ConnectionCheckResult(
                name=connection.name,
                connected=False,
                message=f"Unexpected SMB error: {exc!s}",
                exception=str(exc),
            )
        finally:
            if client is not None:
                client.close()

    async def get_client(self, connection: ValidatedConnection) -> SMBProtocolClient:
        properties = connection.properties
        secrets = connection.secrets

        if not isinstance(properties, SMBProtocolProperties):
            raise InfrastructureError(
                "SMB connection properties payload is invalid.",
                details={"received_type": type(properties).__name__},
            )
        if not isinstance(secrets, SMBProtocolSecrets):
            raise InfrastructureError(
                "SMB connection secrets payload is invalid.",
                details={"received_type": type(secrets).__name__},
            )

        return SMBProtocolClient(
            host=properties.host,
            port=properties.port,
            share=properties.share,
            username=properties.username,
            password=secrets.password,
        )

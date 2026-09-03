# Gateway SDK

Async-first Python SDK for `services/gateway`, with a mirrored sync client.

## Install Context

This package lives inside the DVT repository at `src/clients/gateway_sdk`.

## Quick Start

```python
from src.clients.gateway_sdk import DVTClient


async def main() -> None:
    client = DVTClient(
        base_url="http://127.0.0.1:8200/api",
        username="admin@example.com",
        password="Secret123",
        timeout=30.0,
    )

    try:
        created = await client.db_connections.create(
            data={
                "name": "sdk-postgres",
                "kind": "sql",
                "type": "postgres",
                "driver": "psycopg",
                "properties": {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "username": "postgres",
                    "database": "postgres",
                },
                "secrets": {
                    "password": "postgres",
                },
            }
        )

        same_connection = await client.db_connections.retrieve(id=created.id)
        health = await client.db_connections.check_by_id(connection_id=created.id, data={})
        print(same_connection.name, health.connected)
    finally:
        await client.aclose()
```

## Public API Token Flow

```python
from src.clients.gateway_sdk import DVTClient


async def main() -> None:
    client = DVTClient(
        base_url="http://127.0.0.1:8200/api",
        api_token="public-token",
    )

    try:
        organizations = await client.public.organizations.list()
        db_connections = await client.public.db_connections.list(type="postgres")
        print(len(organizations), len(db_connections))
    finally:
        await client.aclose()
```

`api_token` is intended for `/public/*` routes. Private routes should use `username/password` or `access_token`.

## Sync Client

```python
from src.clients.gateway_sdk import DVTSyncClient


with DVTSyncClient(
    base_url="http://127.0.0.1:8200/api",
    access_token="access-token",
) as client:
    config = client.system.runtime_config()
    print(config)
```

## Notable Behaviors

- `client.auth.*` is implemented manually because the mounted auth app returns envelopes that are not fully described by OpenAPI.
- `client.store.set(...)` sends raw UTF-8 body content.
- `client.storage.download.file(...)` and `client.projects.dataframe.download(...)` return `BinaryPayload`.
- Generated resource methods now follow Gateway path structure more closely, for example:
  - `client.storage.upload.file(...)`
  - `client.storage.download.file(...)`
  - `client.projects.tasks.new(...)`
  - `client.projects.cache.clear.execute(...)`
  - `client.app_settings.fields.required.list()`
- Endpoints whose literal path collides with another route may keep a disambiguating name, for example `client.db_connections.check_by_id(...)`.

"""UPD encrypt db-connection passwords

Revision ID: 0010
Revises: 0009
Create Date: 2025-11-07 18:41:46.733048

"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Sequence, Tuple, Union

from alembic import op
from cryptography.fernet import Fernet, InvalidToken
import sqlalchemy as sa
import config


SENSITIVE_FIELDS = {
    "password",
    "sasl_plain_password",
    "access_token_id",
    "access_token_key",
    "session_token",
}

FERNET_PREFIX = "fernet$"


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DB_CONNECTIONS = sa.table(
    "db_connections",
    sa.column("id", sa.String()),
    sa.column("connection_properties", sa.JSON()),
)

Payload = Dict[str, Any]
Mutator = Callable[[Payload, Fernet], Tuple[Payload, bool]]


def _get_cipher() -> Fernet:
    key = config.SECURITY.FERNET_KEY
    if not key:
        raise RuntimeError("FERNET_KEY is not configured.")
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    return Fernet(key_bytes)


def _encrypt_value(value: Any, cipher: Fernet) -> Any:
    if not isinstance(value, str) or value == "":
        return value
    if value.startswith(FERNET_PREFIX):
        return value
    token = cipher.encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{FERNET_PREFIX}{token}"


def _decrypt_value(value: Any, cipher: Fernet) -> Any:
    if not isinstance(value, str):
        return value
    if not value.startswith(FERNET_PREFIX):
        return value
    token = value[len(FERNET_PREFIX):].encode("utf-8")
    try:
        return cipher.decrypt(token).decode("utf-8")
    except InvalidToken:
        return value


def _mutate_payload(payload: Mapping[str, Any], cipher: Fernet,
                    transform: Callable[[Any, Fernet], Any]) -> Tuple[Payload, bool]:
    data: Payload = dict(payload)
    changed = False

    for field in SENSITIVE_FIELDS:
        if field not in data or data[field] in (None, ""):
            continue
        new_value = transform(data[field], cipher)
        if new_value != data[field]:
            data[field] = new_value
            changed = True

    return data, changed


def _process_connections(mutator: Mutator) -> None:
    cipher = _get_cipher()
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(DB_CONNECTIONS.c.id, DB_CONNECTIONS.c.connection_properties)
    ).mappings()

    for row in rows:
        payload = row["connection_properties"]
        if payload is None or not isinstance(payload, Mapping):
            continue
        new_payload, changed = mutator(payload, cipher)
        if not changed:
            continue
        bind.execute(
            sa.update(DB_CONNECTIONS)
            .where(DB_CONNECTIONS.c.id == row["id"])
            .values(connection_properties=new_payload)
        )


def upgrade() -> None:
    """Encrypt existing sensitive connection properties."""

    def do_encrypt(payload: Mapping[str, Any], cipher: Fernet) -> Tuple[Payload, bool]:
        return _mutate_payload(payload, cipher, _encrypt_value)

    _process_connections(do_encrypt)


def downgrade() -> None:
    """Decrypt sensitive connection properties back to plain text."""

    def do_decrypt(payload: Mapping[str, Any], cipher: Fernet) -> Tuple[Payload, bool]:
        return _mutate_payload(payload, cipher, _decrypt_value)

    _process_connections(do_decrypt)

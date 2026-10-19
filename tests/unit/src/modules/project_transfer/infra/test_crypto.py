from __future__ import annotations

import pytest

from src.modules.project_transfer.domain.exceptions import (
    InvalidBundleError,
    InvalidPassphraseError,
)
from src.modules.project_transfer.infra.crypto import PassphraseSecretsCipher


def test_round_trip_and_wrong_passphrase():
    cipher = PassphraseSecretsCipher()
    payload = {"connection-1": {"password": "s3cret", "token": "абв"}}

    blob = cipher.encrypt(payload, passphrase="correct horse")

    assert blob.startswith(b"DVTS")
    assert b"s3cret" not in blob
    assert cipher.decrypt(blob, passphrase="correct horse") == payload
    with pytest.raises(InvalidPassphraseError):
        cipher.decrypt(blob, passphrase="wrong horse")


def test_tampered_header_or_ciphertext_is_rejected():
    cipher = PassphraseSecretsCipher()
    blob = cipher.encrypt({"c": {"k": "v"}}, passphrase="passphrase1")

    tampered_body = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(InvalidPassphraseError):
        cipher.decrypt(tampered_body, passphrase="passphrase1")

    with pytest.raises(InvalidBundleError):
        cipher.decrypt(b"not a secrets blob", passphrase="passphrase1")

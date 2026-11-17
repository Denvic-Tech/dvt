"""Passphrase-based protection of exported connection secrets.

Blob layout: ``DVTS`` magic, one byte header length (big-endian uint16), JSON header
with KDF parameters, salt and nonce, then AES-256-GCM ciphertext. The header is
bound to the ciphertext as associated data, so tampering with parameters fails
decryption.
"""

from __future__ import annotations

import json
import os
import struct
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from src.modules.project_transfer.domain.exceptions import (
    InvalidBundleError,
    InvalidPassphraseError,
)

_MAGIC = b"DVTS"
_KEY_LENGTH = 32
_SALT_LENGTH = 16
_NONCE_LENGTH = 12
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_MAX_SCRYPT_N = 2**20


class PassphraseSecretsCipher:
    def encrypt(self, payload: dict[str, Any], *, passphrase: str) -> bytes:
        salt = os.urandom(_SALT_LENGTH)
        nonce = os.urandom(_NONCE_LENGTH)
        header = {
            "kdf": "scrypt",
            "n": _SCRYPT_N,
            "r": _SCRYPT_R,
            "p": _SCRYPT_P,
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "cipher": "aes-256-gcm",
        }
        header_bytes = json.dumps(header, sort_keys=True).encode("utf-8")
        key = self._derive_key(passphrase, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            header_bytes,
        )
        return _MAGIC + struct.pack(">H", len(header_bytes)) + header_bytes + ciphertext

    def decrypt(self, blob: bytes, *, passphrase: str) -> dict[str, Any]:
        header_bytes, ciphertext, header = self._split(blob)
        try:
            salt = bytes.fromhex(header["salt"])
            nonce = bytes.fromhex(header["nonce"])
            n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidBundleError("Secrets header is malformed") from exc
        if header.get("kdf") != "scrypt" or header.get("cipher") != "aes-256-gcm":
            raise InvalidBundleError("Secrets use an unsupported cipher")
        if n <= 1 or n > _MAX_SCRYPT_N or r <= 0 or p <= 0:
            raise InvalidBundleError("Secrets KDF parameters are out of range")

        key = self._derive_key(passphrase, salt, n, r, p)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, header_bytes)
        except InvalidTag as exc:
            raise InvalidPassphraseError() from exc
        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except ValueError as exc:
            raise InvalidBundleError("Decrypted secrets are not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidBundleError("Decrypted secrets must be an object")
        return payload

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        return Scrypt(salt=salt, length=_KEY_LENGTH, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))

    @staticmethod
    def _split(blob: bytes) -> tuple[bytes, bytes, dict[str, Any]]:
        if not blob.startswith(_MAGIC) or len(blob) < len(_MAGIC) + 2:
            raise InvalidBundleError("Secrets blob has an unknown format")
        (header_length,) = struct.unpack(">H", blob[len(_MAGIC) : len(_MAGIC) + 2])
        header_start = len(_MAGIC) + 2
        header_end = header_start + header_length
        if len(blob) <= header_end:
            raise InvalidBundleError("Secrets blob is truncated")
        header_bytes = blob[header_start:header_end]
        try:
            header = json.loads(header_bytes.decode("utf-8"))
        except ValueError as exc:
            raise InvalidBundleError("Secrets header is not valid JSON") from exc
        if not isinstance(header, dict):
            raise InvalidBundleError("Secrets header must be an object")
        return header_bytes, blob[header_end:], header

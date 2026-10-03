"""
Encryption at rest for the numbers that identify a person to a government or a bank
(Aadhaar, PAN, UAN, PF, ESI, passport, driving licence, voter ID, bank account).

Columns declared with `EncryptedString` are encrypted on write and decrypted on read, so the
code above them sees plain values and a database dump, backup or stray SELECT does not.

- AES-256-GCM, a fresh 96-bit nonce per value, the column name as associated data (a value
  copied into another column fails to decrypt).
- Stored as `enc:v1:<key id>:<base64url(nonce + ciphertext)>`. The key id makes rotation a
  matter of adding a key: values are read with whichever key wrote them and rewritten with
  the active one by `python -m hrms.deploy encrypt-pii`.
- Empty values stay empty (NULL / ''), so "is it on file?" counts work on encrypted columns.
- A value without the prefix is a row written before encryption: it is returned as-is until
  `encrypt-pii` rewrites it.

Keys come from HRMS_FIELD_ENCRYPTION_KEYS ("<id>:<base64url 32 bytes>", comma-separated,
first = active). That is the KeyProvider seam: an AWS KMS provider can replace it without
touching the columns. Testing and production refuse to start without a key of their own
(core/config.py). Locally, with no key configured, values are written as they are (reads
still understand encrypted ones, with the published development key) — so a developer
database, or one not yet migrated for the longer encrypted values, behaves as before.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

PREFIX = "enc:v1:"
# Published on purpose (it's in the repository): only ever valid with HRMS_ENVIRONMENT=local.
DEV_KEY_ID = "dev"
DEV_KEYS = DEV_KEY_ID + ":" + base64.urlsafe_b64encode(b"hrms-local-development-only-key!").decode()


class FieldCryptoError(ValueError):
    pass


def parse_keys(spec: str) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        key_id, sep, encoded = part.partition(":")
        if not sep or not key_id or ":" in key_id:
            raise FieldCryptoError("HRMS_FIELD_ENCRYPTION_KEYS entries are <id>:<base64url key>")
        try:
            key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except ValueError as exc:
            raise FieldCryptoError(f"key {key_id!r} is not base64url") from exc
        if len(key) != 32:
            raise FieldCryptoError(f"key {key_id!r} must be 32 bytes (AES-256), not {len(key)}")
        if key_id in keys:
            raise FieldCryptoError(f"key id {key_id!r} is listed twice")
        keys[key_id] = key
    if not keys:
        raise FieldCryptoError("no field encryption key configured")
    return keys


class FieldCipher:
    def __init__(self, spec: str):
        keys = parse_keys(spec)
        self.active_id = next(iter(keys))
        self._aead = {key_id: AESGCM(key) for key_id, key in keys.items()}

    def encrypt(self, value: str, column: str) -> str:
        nonce = os.urandom(12)
        sealed = self._aead[self.active_id].encrypt(nonce, value.encode(), column.encode())
        token = base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")
        return f"{PREFIX}{self.active_id}:{token}"

    def decrypt(self, stored: str, column: str) -> str:
        if not stored.startswith(PREFIX):
            return stored  # written before encryption; encrypt-pii rewrites it
        key_id, _, token = stored[len(PREFIX):].partition(":")
        aead = self._aead.get(key_id)
        if aead is None:
            raise FieldCryptoError(f"value was encrypted with key {key_id!r}: not configured")
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        try:
            return aead.decrypt(raw[:12], raw[12:], column.encode()).decode()
        except Exception as exc:  # InvalidTag: wrong key, wrong column or tampered
            raise FieldCryptoError(f"{column}: does not decrypt (wrong key or tampered)") from exc

    def needs_rewrite(self, stored: str | None) -> bool:
        """Plaintext, or encrypted with a key that is no longer the active one."""
        if not stored:
            return False
        return not stored.startswith(f"{PREFIX}{self.active_id}:")


@lru_cache(maxsize=4)
def _cipher_for(spec: str) -> FieldCipher:
    return FieldCipher(spec)


def cipher() -> FieldCipher:
    """For reading (and rewriting): the configured keys, else the development key."""
    from hrms.core.config import settings

    return _cipher_for(settings.field_encryption_keys or DEV_KEYS)


def write_cipher() -> FieldCipher | None:
    """For writing: only when keys are configured (always, outside local — see config)."""
    from hrms.core.config import settings

    return _cipher_for(settings.field_encryption_keys) if settings.field_encryption_keys else None


class EncryptedString(TypeDecorator):
    """A text column stored encrypted (see the module docstring). `column` is the AAD."""

    impl = Text
    cache_ok = True

    def __init__(self, column: str):
        super().__init__()
        self.column = column

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return value
        if isinstance(value, str) and value.startswith(PREFIX):
            return value  # already encrypted (e.g. copied row to row by encrypt-pii)
        c = write_cipher()
        return c.encrypt(str(value), self.column) if c else value

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        return cipher().decrypt(value, self.column)

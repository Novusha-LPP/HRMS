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
from decimal import Decimal
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
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
        if not sep or not key_id or ":" in key_id or len(key_id.encode()) > 255:
            raise FieldCryptoError("HRMS_FIELD_ENCRYPTION_KEYS entries are <id>:<base64url key>")
        try:
            key = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
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
    """
    With `pepper` (payroll), the AES key is not the configured key itself but
    HKDF-SHA256(key, salt=pepper, info=purpose|key id|column): the configured key alone, or
    the pepper alone, decrypts nothing, and every column has a key of its own. Without it
    (identifiers) the configured key is used directly, exactly as before.
    """

    def __init__(
        self, spec: str, *, prefix: str = PREFIX, pepper: str | None = None, purpose: str = ""
    ):
        self._keys = parse_keys(spec)
        self.active_id = next(iter(self._keys))
        self.prefix = prefix
        self._pepper = pepper.encode() if pepper else None
        self._purpose = purpose
        self._aeads: dict[tuple[str, str], AESGCM] = {}

    def _aead_for(self, key_id: str, column: str) -> AESGCM | None:
        raw = self._keys.get(key_id)
        if raw is None:
            return None
        if self._pepper is None:
            return AESGCM(raw)
        cached = self._aeads.get((key_id, column))
        if cached is None:
            info = f"{self._purpose}|{key_id}|{column}".encode()
            derived = HKDF(hashes.SHA256(), 32, salt=self._pepper, info=info).derive(raw)
            cached = self._aeads[(key_id, column)] = AESGCM(derived)
        return cached

    def encrypt(self, value: str, column: str) -> str:
        nonce = os.urandom(12)
        aead = self._aead_for(self.active_id, column)
        assert aead is not None  # the active id is always one of the configured keys
        sealed = aead.encrypt(nonce, value.encode(), column.encode())
        token = base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")
        return f"{self.prefix}{self.active_id}:{token}"

    def is_sealed(self, stored: str | None) -> bool:
        return stored is not None and stored.startswith(self.prefix)

    def decrypt(self, stored: str, column: str) -> str:
        if not stored.startswith(self.prefix):
            return stored  # written before encryption; the rewrite command seals it
        key_id, _, token = stored[len(self.prefix) :].partition(":")
        aead = self._aead_for(key_id, column)
        if aead is None:
            raise FieldCryptoError(f"value was encrypted with key {key_id!r}: not configured")
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            if len(raw) < 28:
                raise ValueError("Truncated ciphertext")
            return aead.decrypt(raw[:12], raw[12:], column.encode()).decode()
        except Exception as exc:  # InvalidTag: wrong key, wrong column or tampered
            raise FieldCryptoError(f"{column}: does not decrypt (wrong key or tampered)") from exc

    def needs_rewrite(self, stored: str | None) -> bool:
        """Plaintext, or encrypted with a key that is no longer the active one."""
        if not stored:
            return False
        return not stored.startswith(f"{self.prefix}{self.active_id}:")


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


# --- Payroll -------------------------------------------------------------------------------
# Salaries are protected apart from the identifiers above: their own keys
# (HRMS_PAYROLL_ENCRYPTION_KEYS) and a pepper (HRMS_PAYROLL_PEPPER) that lives in a different
# secret from both the keys and the database. Whoever can read the database, a backup, the
# identifier keys or the pepper alone learns no salary. Each value also carries its own random
# 96-bit nonce (the per-value salt), so equal salaries look different.

PAYROLL_PREFIX = "pay:v1:"
PAYROLL_PURPOSE = "hrms-payroll-v1"
# Published on purpose, like DEV_KEYS: only ever valid with HRMS_ENVIRONMENT=local.
DEV_PAYROLL_KEYS = (
    DEV_KEY_ID + ":" + base64.urlsafe_b64encode(b"hrms-local-payroll-dev-only-key!").decode()
)
DEV_PAYROLL_PEPPER = "hrms-local-payroll-development-pepper"
MIN_PEPPER_LENGTH = 32


@lru_cache(maxsize=4)
def _payroll_cipher_for(spec: str, pepper: str) -> FieldCipher:
    return FieldCipher(spec, prefix=PAYROLL_PREFIX, pepper=pepper, purpose=PAYROLL_PURPOSE)


def payroll_cipher() -> FieldCipher:
    """For reading (and rewriting): the configured payroll keys, else the development ones."""
    from hrms.core.config import settings

    return _payroll_cipher_for(
        settings.payroll_encryption_keys or DEV_PAYROLL_KEYS,
        settings.payroll_pepper or DEV_PAYROLL_PEPPER,
    )


def payroll_write_cipher() -> FieldCipher | None:
    from hrms.core.config import settings

    if not settings.payroll_encryption_keys:
        return None
    return _payroll_cipher_for(settings.payroll_encryption_keys, settings.payroll_pepper or "")


def seal_amount(value: Decimal | str | None, column: str) -> str | None:
    """An amount as stored (a sealed token when payroll keys are configured)."""
    if value is None:
        return None
    c = payroll_write_cipher()
    return c.encrypt(str(value), column) if c else str(value)


def open_amount(stored: str | Decimal | None, column: str) -> Decimal | None:
    if stored is None or stored == "":
        return None
    if isinstance(stored, Decimal):
        return stored
    return Decimal(payroll_cipher().decrypt(str(stored), column))


class EncryptedDecimal(TypeDecorator):
    """A money column stored as a sealed token (see above). `column` is the associated data.

    The database cannot add, compare or sort these: payroll does that in Python.
    """

    impl = Text
    cache_ok = True

    def __init__(self, column: str):
        super().__init__()
        self.column = column

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(PAYROLL_PREFIX):
            return value
        return seal_amount(Decimal(value).quantize(Decimal("0.01")), self.column)

    def process_result_value(self, value, dialect):
        return open_amount(value, self.column)

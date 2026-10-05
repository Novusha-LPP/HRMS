"""
Where uploaded documents (KYC scans of Aadhaar, PAN, bank proof, …) are kept, encrypted.

- Every file is encrypted before it is stored (whenever keys are configured — always outside
  local development), with the same keys as the identifiers
  (core/field_crypto.py, HRMS_FIELD_ENCRYPTION_KEYS): AES-256-GCM, a fresh nonce, the
  storage key as associated data (a file moved under another document's name won't open).
  Layout: b"HRMSDOC1" | key-id length (1 byte) | key id | nonce (12) | ciphertext.
- Backends: `local` (a directory, HRMS_STORAGE_DIR) or `s3` (HRMS_DOCUMENT_S3_BUCKET; any
  S3-compatible store). The database records `doc:<key>`, never a server path, so the same
  rows work with either backend.
- Rows from before this store hold a filesystem path instead of `doc:…`, and their files are
  plain. They are still served; `python -m hrms.deploy encrypt-pii` encrypts them in place.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hrms.core.field_crypto import FieldCryptoError, cipher, parse_keys

REF_PREFIX = "doc:"
MAGIC = b"HRMSDOC1"


# ─── Encryption ──────────────────────────────────────────────────────────────


def _keys() -> dict[str, bytes]:
    from hrms.core.config import settings
    from hrms.core.field_crypto import DEV_KEYS

    return parse_keys(settings.field_encryption_keys or DEV_KEYS)


def seal(data: bytes, aad: str) -> bytes:
    key_id = cipher().active_id
    nonce = os.urandom(12)
    sealed = AESGCM(_keys()[key_id]).encrypt(nonce, data, aad.encode())
    kid = key_id.encode()
    return MAGIC + bytes([len(kid)]) + kid + nonce + sealed


def is_sealed(blob: bytes) -> bool:
    return blob.startswith(MAGIC)


def _sealed_parts(blob: bytes) -> tuple[str, bytes, bytes]:
    """Reject malformed envelopes through the same error contract as AES failures."""
    try:
        if len(blob) <= len(MAGIC):
            raise ValueError("Truncated header")
        n = blob[len(MAGIC)]
        start = len(MAGIC) + 1
        if not n or len(blob) < start + n + 12 + 16:
            raise ValueError("Truncated ciphertext")
        return (blob[start:start + n].decode("utf-8"),
                blob[start + n:start + n + 12], blob[start + n + 12:])
    except (ValueError, IndexError, UnicodeError) as exc:
        raise FieldCryptoError("Malformed encrypted document") from exc


def sealed_key_id(blob: bytes) -> str | None:
    if not is_sealed(blob):
        return None
    return _sealed_parts(blob)[0]


def unseal(blob: bytes, aad: str) -> bytes:
    if not is_sealed(blob):
        return blob  # Legacy plaintext remains readable until migration.
    key_id, nonce, sealed = _sealed_parts(blob)
    key = _keys().get(key_id)
    if key is None:
        raise FieldCryptoError(f"document was encrypted with key {key_id!r}: not configured")
    try:
        return AESGCM(key).decrypt(nonce, sealed, aad.encode())
    except Exception as exc:
        raise FieldCryptoError("document does not decrypt (wrong key or tampered)") from exc


# ─── Backends ────────────────────────────────────────────────────────────────


class Backend(Protocol):
    def put(self, key: str, blob: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalBackend:
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("document key escapes the storage directory")
        return path

    def put(self, key: str, blob: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_bytes(blob)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise DocumentMissing(key) from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Backend:
    def __init__(self, bucket: str, prefix: str = "", **client_kwargs):
        import boto3  # only needed when HRMS_DOCUMENT_STORAGE=s3
        from botocore.config import Config

        from hrms.core.config import settings

        self.bucket, self.prefix = bucket, prefix.strip("/")
        self.client = boto3.client(
            "s3",
            config=Config(connect_timeout=5, read_timeout=settings.document_timeout_seconds,
                          retries={"mode": "standard", "total_max_attempts": 3}),
            **{k: v for k, v in client_kwargs.items() if v},
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, blob: bytes) -> None:
        # Server-side encryption too, on top of ours: the bucket never holds a readable byte.
        self.client.put_object(
            Bucket=self.bucket, Key=self._key(key), Body=blob, ServerSideEncryption="AES256"
        )

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read()
        except self.client.exceptions.NoSuchKey as exc:
            raise DocumentMissing(key) from exc

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


class DocumentMissing(LookupError):
    pass


_backend: Backend | None = None
_backend_config: tuple | None = None


def backend() -> Backend:
    global _backend, _backend_config
    from hrms.core.config import settings

    config = (
        settings.document_storage,
        settings.storage_dir,
        settings.document_s3_bucket,
        settings.document_s3_prefix,
        settings.document_s3_region,
        settings.document_s3_endpoint_url,
    )
    if _backend is None or config != _backend_config:
        if settings.document_storage == "s3":
            _backend = S3Backend(
                settings.document_s3_bucket or "",
                settings.document_s3_prefix,
                region_name=settings.document_s3_region,
                endpoint_url=settings.document_s3_endpoint_url,
            )
        else:
            _backend = LocalBackend(settings.storage_dir)
        _backend_config = config
    return _backend


# ─── The API the application uses ────────────────────────────────────────────


def save(key: str, data: bytes) -> str:
    """Encrypt (when keys are configured) and store; returns the reference for the database."""
    from hrms.core.field_crypto import write_cipher

    backend().put(key, seal(data, key) if write_cipher() else data)
    return REF_PREFIX + key


def load(ref: str) -> bytes:
    """The plain bytes of a stored document (or of a pre-encryption file at a path)."""
    if ref.startswith(REF_PREFIX):
        key = ref[len(REF_PREFIX) :]
        return unseal(backend().get(key), key)
    try:
        return Path(ref).read_bytes()  # legacy row: a plain file at a server path
    except FileNotFoundError as exc:
        raise DocumentMissing(ref) from exc


def remove(ref: str) -> None:
    if ref.startswith(REF_PREFIX):
        backend().delete(ref[len(REF_PREFIX) :])
    else:
        Path(ref).unlink(missing_ok=True)

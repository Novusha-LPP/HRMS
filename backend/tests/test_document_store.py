"""Uploaded documents are encrypted at rest (core/document_store.py)."""

from pathlib import Path

import pytest
from sqlalchemy import text

from hrms.core import document_store as store
from hrms.core.config import settings
from hrms.core.field_crypto import FieldCryptoError
from hrms.core.ids import to_uuid
from hrms.deploy import _rewrite_pii
from tests.helpers import ok

SCAN = b"%PDF-1.4 an Aadhaar card scan 1234 5678 9012"


def test_sealing_binds_the_file_to_its_place():
    blob = store.seal(SCAN, "kyc/t/a.pdf")
    assert store.is_sealed(blob) and SCAN not in blob
    assert store.unseal(blob, "kyc/t/a.pdf") == SCAN
    with pytest.raises(FieldCryptoError):
        store.unseal(blob, "kyc/t/b.pdf")  # moved under another document's name
    assert store.unseal(SCAN, "anything") == SCAN  # a file from before encryption


def test_local_keys_cannot_escape_the_storage_directory(tmp_path):
    backend = store.LocalBackend(str(tmp_path))
    with pytest.raises(ValueError):
        backend.put("../../etc/evil", b"x")


@pytest.mark.database
async def test_uploads_are_encrypted_and_old_files_are_converted(api):
    from tests.test_kyc_privacy import _setup

    client, engine = api
    _, tokens = await _setup(client)
    doc = await ok(
        client,
        "POST",
        "/v1/kyc/me/documents",
        headers=tokens["self"],
        files={"file": ("aadhaar.pdf", SCAN, "application/pdf")},
        data={"document_type": "AADHAAR_FRONT", "document_title": "Aadhaar"},
    )
    url = f"/v1/kyc/documents/{doc['id']}/download"

    async def row():
        async with engine.begin() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT tenant_id, storage_path FROM employee_kyc_documents WHERE id = :d"
                    ),
                    {"d": to_uuid(doc["id"])},
                )
            ).one()

    tenant_id, ref = await row()
    assert ref.startswith("doc:kyc/")
    on_disk = (Path(settings.storage_dir) / ref[len("doc:") :]).read_bytes()
    assert store.is_sealed(on_disk) and b"1234 5678 9012" not in on_disk
    download = await client.get(url, headers=tokens["self"])
    assert download.status_code == 200 and download.content == SCAN
    assert download.headers["cache-control"] == "private, no-store"

    # A file stored before encryption: plain, at a server path. Served, then converted.
    legacy = Path(settings.storage_dir) / "legacy" / "old-scan.pdf"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(SCAN)
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        await conn.execute(
            text("UPDATE employee_kyc_documents SET storage_path = :p WHERE id = :d"),
            {"p": str(legacy), "d": to_uuid(doc["id"])},
        )
    assert (await client.get(url, headers=tokens["self"])).content == SCAN
    assert await _rewrite_pii(check=True) >= 1
    await _rewrite_pii(check=False)
    _, ref = await row()
    assert ref.startswith("doc:") and not legacy.exists()
    assert store.is_sealed((Path(settings.storage_dir) / ref[len("doc:") :]).read_bytes())
    assert (await client.get(url, headers=tokens["self"])).content == SCAN
    assert await _rewrite_pii(check=True) == 0


def test_without_a_key_locally_files_are_stored_as_they_are(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "field_encryption_keys", None)
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    ref = store.save("kyc/t/plain.pdf", SCAN)
    assert (tmp_path / "kyc/t/plain.pdf").read_bytes() == SCAN and store.load(ref) == SCAN

"""Identifiers are encrypted at rest (core/field_crypto.py) and existing rows can be converted."""

import base64
import os

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from hrms.core import field_crypto
from hrms.core.config import Settings
from hrms.core.field_crypto import EncryptedString, FieldCipher, FieldCryptoError
from hrms.deploy import ENCRYPTED_COLUMNS, _rewrite_pii
from tests.helpers import ok


def _key(key_id: str) -> str:
    return f"{key_id}:" + base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_round_trip_and_associated_data():
    c = FieldCipher(_key("k1"))
    token = c.encrypt("123456789012", "aadhaar_number")
    assert token.startswith("enc:v1:k1:") and "123456789012" not in token
    assert c.decrypt(token, "aadhaar_number") == "123456789012"
    # The same plaintext encrypts differently every time (fresh nonce).
    assert c.encrypt("123456789012", "aadhaar_number") != token
    # Copied into another column, or tampered with, it doesn't decrypt.
    with pytest.raises(FieldCryptoError):
        c.decrypt(token, "pan_number")
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    with pytest.raises(FieldCryptoError):
        c.decrypt(tampered, "aadhaar_number")


def test_rotation_reads_old_keys_and_marks_their_values_for_rewrite():
    old, new = _key("2026a"), _key("2026b")
    written = FieldCipher(old).encrypt("ABCDE1234F", "pan_number")
    rotated = FieldCipher(f"{new},{old}")
    assert rotated.decrypt(written, "pan_number") == "ABCDE1234F"
    assert rotated.needs_rewrite(written) and rotated.needs_rewrite("ABCDE1234F")
    assert not rotated.needs_rewrite(rotated.encrypt("x", "pan_number"))
    assert not rotated.needs_rewrite(None) and not rotated.needs_rewrite("")
    with pytest.raises(FieldCryptoError, match="not configured"):
        FieldCipher(new).decrypt(written, "pan_number")


def test_plain_values_from_before_encryption_read_as_they_are():
    assert FieldCipher(_key("k")).decrypt("ABCDE1234F", "pan_number") == "ABCDE1234F"


@pytest.mark.parametrize(
    "spec", ["", "nokey", "k:" + base64.urlsafe_b64encode(b"short").decode(), "a:x,a:x"]
)
def test_bad_key_specs_are_rejected(spec):
    with pytest.raises(FieldCryptoError):
        FieldCipher(spec)


DEPLOYED = dict(
    _env_file=None,
    environment="production",
    secret_key="x" * 40,
    database_url="postgresql+asyncpg://owner:strong@db/hrms",
    app_database_url="postgresql+asyncpg://hrms_app:strong@db/hrms",
    platform_database_url="postgresql+asyncpg://hrms_platform:strong@db/hrms",
    metrics_token="scrape",
    cors_origins="https://hrms.example.com",
)


def test_deployed_environments_need_their_own_key():
    with pytest.raises(ValidationError, match="HRMS_FIELD_ENCRYPTION_KEYS"):
        Settings(**DEPLOYED)
    with pytest.raises(ValidationError, match="development key"):
        Settings(**DEPLOYED, field_encryption_keys=field_crypto.DEV_KEYS)
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings(**DEPLOYED, field_encryption_keys="k:" + base64.urlsafe_b64encode(b"x").decode())
    Settings(
        **DEPLOYED,
        field_encryption_keys=_key("prod-1"),
        payroll_encryption_keys=_key("pay-1"),
        payroll_pepper="p" * 40,
    )


def test_the_rewrite_command_covers_every_encrypted_column():
    from hrms.model_registry import metadata

    declared = {
        table.name: tuple(c.name for c in table.c if isinstance(c.type, EncryptedString))
        for table in metadata.tables.values()
    }
    declared = {t: cols for t, cols in declared.items() if cols}
    assert {t: set(c) for t, c in declared.items()} == {
        t: set(c) for t, c in ENCRYPTED_COLUMNS.items()
    }


@pytest.mark.database
async def test_stored_encrypted_converted_in_place_and_rotated(api, monkeypatch):
    from tests.test_kyc_privacy import KYC, _setup

    client, engine = api
    subject, tokens = await _setup(client)

    from hrms.core.ids import to_uuid

    eid = to_uuid(subject["id"])

    async def stored():
        async with engine.begin() as conn:
            return (
                await conn.execute(
                    text("""SELECT tenant_id, pan_number, aadhaar_number, account_number
                            FROM employee_kyc_records WHERE employment_id = :e"""),
                    {"e": eid},
                )
            ).mappings().one()

    # Written through the API: encrypted in the database, plain to the owner.
    row = await stored()
    for column in ("pan_number", "aadhaar_number", "account_number"):
        assert row[column].startswith("enc:v1:dev:") and KYC[column] not in row[column]
    own = await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"])
    assert own["aadhaar_number"] == KYC["aadhaar_number"]

    # A row from before encryption: plain in the database, still readable, then converted.
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(row["tenant_id"])}
        )
        await conn.execute(
            text("UPDATE employee_kyc_records SET aadhaar_number = '999988887777' "
                 "WHERE employment_id = :e"),
            {"e": eid},
        )
    assert (await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"]))[
        "aadhaar_number"
    ] == "999988887777"
    assert await _rewrite_pii(check=True) >= 1
    await _rewrite_pii(check=False)
    assert await _rewrite_pii(check=True) == 0
    assert (await stored())["aadhaar_number"].startswith("enc:v1:")

    # Rotation: a new active key, the old one kept to read; encrypt-pii moves everything over.
    new = _key("2026-10")
    monkeypatch.setattr(
        "hrms.core.config.settings.field_encryption_keys", f"{new},{field_crypto.DEV_KEYS}"
    )
    assert await _rewrite_pii(check=True) >= 3
    await _rewrite_pii(check=False)
    assert (await stored())["pan_number"].startswith("enc:v1:2026-10:")
    assert (await ok(client, "GET", "/v1/kyc/me", headers=tokens["self"]))[
        "pan_number"
    ] == KYC["pan_number"]

    # Taking the old key away while values still need it is reported, not a crash.
    monkeypatch.setattr("hrms.core.config.settings.field_encryption_keys", _key("other"))
    from hrms.deploy import UnreadableValues

    with pytest.raises(UnreadableValues, match="employee_kyc_records"):
        await _rewrite_pii(check=True)

    # Back to the default key, so the shared test database stays readable for other tests.
    monkeypatch.setattr(
        "hrms.core.config.settings.field_encryption_keys", f"{field_crypto.DEV_KEYS},{new}"
    )
    await _rewrite_pii(check=False)
    assert (await stored())["pan_number"].startswith("enc:v1:dev:")

    # "Is it on file?" counts still work on encrypted columns.
    hr = await ok(client, "GET", "/v1/dashboard/hr?sections=statutory")
    assert "statutory" in hr


def test_without_a_key_locally_writes_stay_plain_and_reads_still_decrypt(monkeypatch):
    # A developer database, or one not yet migrated for the longer encrypted values (the
    # 0030 widening), must keep working exactly as before until a key is configured.
    monkeypatch.setattr("hrms.core.config.settings.field_encryption_keys", None)
    column = EncryptedString("aadhaar_number")
    assert column.process_bind_param("123412341234", None) == "123412341234"
    stored = FieldCipher(field_crypto.DEV_KEYS).encrypt("123412341234", "aadhaar_number")
    assert column.process_result_value(stored, None) == "123412341234"
    assert field_crypto.write_cipher() is None

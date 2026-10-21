"""Salaries are encrypted at rest with payroll-only keys and a pepper (core/field_crypto.py)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from hrms.core.config import Settings, settings
from hrms.core.field_crypto import FieldCipher, FieldCryptoError, payroll_cipher
from hrms.core.ids import to_uuid
from hrms.deploy import PAYROLL_COLUMNS, _rewrite_payroll
from tests.helpers import ok, person_and_employment, tenant
from tests.test_field_crypto import DEPLOYED, _key
from tests.test_payroll_foundation import _setup

PEPPER = "p" * 40


def _cipher(spec: str, pepper: str = PEPPER) -> FieldCipher:
    return FieldCipher(spec, prefix="pay:v1:", pepper=pepper, purpose="hrms-payroll-v1")


def test_round_trip_salt_and_column_binding():
    spec = _key("p1")
    c = _cipher(spec)
    token = c.encrypt("720000.00", "annual_ctc")
    assert token.startswith("pay:v1:p1:") and "720000" not in token
    assert c.decrypt(token, "annual_ctc") == "720000.00"
    # A fresh random nonce per value: equal salaries do not look equal.
    assert c.encrypt("720000.00", "annual_ctc") != token
    with pytest.raises(FieldCryptoError):
        c.decrypt(token, "bonus")


def test_the_key_alone_or_the_pepper_alone_decrypts_nothing():
    spec = _key("p1")
    token = _cipher(spec).encrypt("720000.00", "annual_ctc")
    with pytest.raises(FieldCryptoError):
        _cipher(spec, "q" * 40).decrypt(token, "annual_ctc")  # right key, wrong pepper
    with pytest.raises(FieldCryptoError):
        _cipher(_key("p1")).decrypt(token, "annual_ctc")  # right pepper, wrong key
    # The identifier cipher (no pepper) cannot read it either, nor the reverse.
    with pytest.raises(FieldCryptoError):
        FieldCipher(spec, prefix="pay:v1:").decrypt(token, "annual_ctc")


def test_payroll_rotation():
    old, new = _key("a"), _key("b")
    token = _cipher(old).encrypt("100.00", "annual_ctc")
    rotated = _cipher(f"{new},{old}")
    assert rotated.decrypt(token, "annual_ctc") == "100.00"
    assert rotated.needs_rewrite(token) and rotated.needs_rewrite("100.00")
    assert not rotated.needs_rewrite(rotated.encrypt("1.00", "annual_ctc"))


def test_deployed_environments_need_payroll_keys_and_a_pepper_of_their_own():
    ident = _key("prod-1")
    base = {**DEPLOYED, "field_encryption_keys": ident}
    with pytest.raises(ValidationError, match="HRMS_PAYROLL_ENCRYPTION_KEYS"):
        Settings(**base)
    with pytest.raises(ValidationError, match="HRMS_PAYROLL_ENCRYPTION_KEYS"):
        Settings(
            **base,
            payroll_encryption_keys=ident.replace("prod-1", "pay-1"),
            payroll_pepper=PEPPER,
        )
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(**base, payroll_encryption_keys=_key("pay-1"), payroll_pepper="short")
    with pytest.raises(ValidationError, match="development key"):
        Settings(**base, payroll_encryption_keys=_key("dev"), payroll_pepper=PEPPER)
    Settings(**base, payroll_encryption_keys=_key("pay-1"), payroll_pepper=PEPPER)


def test_the_rewrite_command_covers_every_encrypted_money_column():
    from hrms.core.field_crypto import EncryptedDecimal
    from hrms.model_registry import metadata

    declared = {
        t.name: {c.name for c in t.c if isinstance(c.type, EncryptedDecimal)}
        for t in metadata.tables.values()
    }
    assert {t: c for t, c in declared.items() if c} == {
        t: set(c) for t, c in PAYROLL_COLUMNS.items()
    }


@pytest.mark.database
async def test_salary_is_sealed_in_the_database_and_the_change_log(api, monkeypatch):
    monkeypatch.setattr(settings, "payroll_encryption_keys", _key("pay-1"))
    monkeypatch.setattr(settings, "payroll_pepper", PEPPER)
    client, engine = api
    await tenant(client)
    le, structure = await _setup(client)
    emp = await person_and_employment(client, le)
    path = f"/v1/payroll/employees/{emp['id']}/compensation"
    body = {"structure_id": structure["id"], "annual_ctc": "600000", "effective_from": "2020-01-01"}
    await ok(client, "POST", path, json=body)
    await ok(
        client, "POST", path, json={**body, "annual_ctc": "720000", "effective_from": "2021-04-01"}
    )

    async def raw():
        async with engine.begin() as conn:
            comp = (
                await conn.execute(
                    text("SELECT tenant_id, id, annual_ctc FROM employee_compensations "
                         "WHERE employment_id = :e ORDER BY effective_from"),
                    {"e": to_uuid(emp["id"])},
                )
            ).mappings().all()
            log = (
                await conn.execute(
                    text("SELECT changes::text FROM entity_change_log "
                         "WHERE entity_type = 'employee_compensation' AND entity_id = ANY(:ids)"),
                    {"ids": [r["id"] for r in comp]},
                )
            ).scalars().all()
        return comp, log

    comp, log = await raw()
    assert all(r["annual_ctc"].startswith("pay:v1:pay-1:") for r in comp)
    assert not any(v in r["annual_ctc"] for r in comp for v in ("600000", "720000"))
    assert log and not any(v in entry for entry in log for v in ("600000", "720000"))

    # The API is unchanged for people allowed to see salaries.
    detail = await ok(client, "GET", path)
    assert [h["annual_ctc"] for h in detail["history"]] == ["720000.00", "600000.00"]
    listed = await ok(client, "GET", "/v1/payroll/salaries")
    assert next(r for r in listed if r["employment_id"] == emp["id"])["annual_ctc"] == "720000.00"

    # Rows from before encryption (plain digits, also in the log) still read, then convert.
    async with engine.begin() as conn:
        # The rewrite visits every tenant: drop other tests' rows, sealed under other keys.
        await conn.execute(text("SET LOCAL row_security = off"))
        await conn.execute(
            text("DELETE FROM employee_compensations WHERE tenant_id <> :t"),
            {"t": comp[0]["tenant_id"]},
        )
        await conn.execute(
            text("DELETE FROM entity_change_log WHERE entity_type = 'employee_compensation' "
                 "AND tenant_id <> :t"),
            {"t": comp[0]["tenant_id"]},
        )
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(comp[0]["tenant_id"])}
        )
        await conn.execute(
            text("UPDATE employee_compensations SET annual_ctc = '600000.00' "
                 "WHERE tenant_id = :t AND id = :i"),
            {"t": comp[0]["tenant_id"], "i": comp[0]["id"]},
        )
        await conn.execute(
            text("UPDATE entity_change_log SET changes = jsonb_set(changes, '{annual_ctc}', "
                 "'{\"old\": null, \"new\": \"600000.00\"}') "
                 "WHERE entity_type = 'employee_compensation' AND changes->'annual_ctc'->>'new' "
                 "LIKE 'pay:v1:%' AND changes->'annual_ctc'->'old' = 'null'::jsonb")
        )
    detail = await ok(client, "GET", path)
    assert detail["history"][1]["annual_ctc"] == "600000.00"
    assert await _rewrite_payroll(check=True) >= 1
    await _rewrite_payroll(check=False)
    assert await _rewrite_payroll(check=True) == 0
    comp, _ = await raw()
    assert comp[0]["annual_ctc"].startswith("pay:v1:")
    _, log = await raw()
    assert log and not any("600000" in entry for entry in log)

    # Rotation: a new first key becomes active and everything is rewritten under it.
    monkeypatch.setattr(
        settings, "payroll_encryption_keys", f"{_key('pay-2')},{settings.payroll_encryption_keys}"
    )
    assert payroll_cipher().active_id == "pay-2"
    assert await _rewrite_payroll(check=True) >= 2
    await _rewrite_payroll(check=False)
    comp, log = await raw()
    assert all(r["annual_ctc"].startswith("pay:v1:pay-2:") for r in comp)
    assert (await ok(client, "GET", path))["current"]["annual_ctc"] == "720000.00"
    # Dropping the old key too early is reported, never silently skipped.
    monkeypatch.setattr(settings, "payroll_encryption_keys", _key("pay-3"))
    from hrms.deploy import UnreadableValues

    with pytest.raises(UnreadableValues):
        await _rewrite_payroll(check=True)

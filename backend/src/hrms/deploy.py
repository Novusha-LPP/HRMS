"""
Deployment steps, run by the deploy's one-shot `migrate` service before the API starts:

    python -m hrms.deploy migrate

1. Applies every migration (alembic upgrade head), as the database owner.
2. Sets the hrms_app role's password from HRMS_APP_ROLE_PASSWORD. Migration 0005 creates the
   role with a published development password; a deployed environment must never keep it.
3. Sets the role's timeouts (APP_ROLE_SETTINGS), so nothing can hold locks indefinitely.
4. Runs encrypt-pii (below), so no identifier stays in plain text or under a retired key.

Both are idempotent, so every deploy runs them. And, for the encrypted identifiers
(core/field_crypto.py):

    python -m hrms.deploy encrypt-pii           rewrite plain or old-key values with the
                                                active key (idempotent; counts only)
    python -m hrms.deploy encrypt-pii --check   exit 1 if any value still needs it
    python -m hrms.deploy decrypt-pii           back to plain text, only to downgrade 0030

and the same for salaries (payroll keys + pepper, migration 0073), including the amounts
already written into the change history:

    python -m hrms.deploy encrypt-payroll [--check]
    python -m hrms.deploy decrypt-payroll       only to downgrade 0073
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from hrms.core.config import (
    KNOWN_DEV_APP_ROLE_PASSWORD,
    KNOWN_DEV_PLATFORM_ROLE_PASSWORD,
    settings,
)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
# Goes into a connection URL as-is and into ALTER ROLE as a literal, so keep it simple.
SAFE_PASSWORD = re.compile(r"[A-Za-z0-9_-]{24,}")


def _role_password(variable: str, dev_password: str) -> str | None:
    password = os.environ.get(variable)
    if not password:
        if settings.is_deployed:
            raise SystemExit(f"{variable} is required outside local development")
        return None
    if password == dev_password or not SAFE_PASSWORD.fullmatch(password):
        raise SystemExit(
            f"{variable} must be 24+ characters of A-Z a-z 0-9 _ - "
            "(e.g. `openssl rand -hex 32`) and not the published development password"
        )
    return password


def _app_role_password() -> str | None:
    return _role_password("HRMS_APP_ROLE_PASSWORD", KNOWN_DEV_APP_ROLE_PASSWORD)


def _platform_role_password() -> str | None:
    return _role_password("HRMS_PLATFORM_ROLE_PASSWORD", KNOWN_DEV_PLATFORM_ROLE_PASSWORD)


# Guard rails on the application's role: a runaway query or a transaction left open can't
# hold locks or connections indefinitely. Far above anything measured (the heaviest request,
# a 2,000-employee accrual, takes ~1 s); applied to new connections.
APP_ROLE_SETTINGS = {
    "statement_timeout": "60s",
    "lock_timeout": "10s",
    "idle_in_transaction_session_timeout": "120s",
}


async def _configure_app_role(password: str | None, role: str = "hrms_app") -> None:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            if password:
                # Validated above to [A-Za-z0-9_-], so it can't break out of the literal.
                await conn.execute(text(f"ALTER ROLE {role} PASSWORD '{password}'"))
            for name, value in APP_ROLE_SETTINGS.items():
                await conn.execute(text(f"ALTER ROLE {role} SET {name} = '{value}'"))
    finally:
        await engine.dispose()


def migrate() -> None:
    password = _app_role_password()  # fail before touching the schema
    platform_password = _platform_role_password()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    command.upgrade(config, "head")
    asyncio.run(_configure_app_role(password))
    asyncio.run(_configure_app_role(platform_password, role="hrms_platform"))
    if password:
        print("hrms_app password set from HRMS_APP_ROLE_PASSWORD")
    if platform_password:
        print("hrms_platform password set from HRMS_PLATFORM_ROLE_PASSWORD")
    print("hrms_app limits: " + ", ".join(f"{k}={v}" for k, v in APP_ROLE_SETTINGS.items()))
    # Every deploy leaves no identifier in plain text or under a retired key (idempotent).
    rewritten = asyncio.run(_rewrite_pii(check=False))
    print(f"encrypt-pii: {rewritten} identifier value(s) encrypted with the active key")
    sealed = asyncio.run(_rewrite_payroll(check=False))
    print(f"encrypt-payroll: {sealed} salary value(s) encrypted with the active key")


# Table -> encrypted columns. Must match the EncryptedString columns of the models
# (tests/test_field_crypto.py checks that it does).
ENCRYPTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "employee_kyc_records": (
        "pan_number",
        "aadhaar_number",
        "uan_number",
        "pf_number",
        "esi_number",
        "passport_number",
        "driving_license",
        "voter_id",
        "account_number",
    ),
    "employee_kyc_documents": ("document_number",),
}


async def _rewrite_pii(*, check: bool, decrypt: bool = False) -> int:
    """One transaction per tenant (RLS binds the owner too). Returns the values to change."""
    from hrms.core.field_crypto import PREFIX, FieldCryptoError, cipher

    if not settings.field_encryption_keys and not decrypt:
        if check:
            raise SystemExit("HRMS_FIELD_ENCRYPTION_KEYS is not set: nothing is being encrypted")
        print("encrypt-pii: skipped, HRMS_FIELD_ENCRYPTION_KEYS is not set (local)")
        return 0
    c = cipher()
    engine = create_async_engine(settings.database_url)
    pending = 0
    unreadable: list[str] = []
    try:
        async with engine.connect() as conn:
            tenants = [r[0] for r in await conn.execute(text("SELECT id FROM tenants ORDER BY id"))]
        for tenant_id in tenants:
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                for table, columns in ENCRYPTED_COLUMNS.items():
                    rows = await conn.execute(
                        text(f"SELECT id, {', '.join(columns)} FROM {table} WHERE tenant_id = :t"),
                        {"t": str(tenant_id)},
                    )
                    for row in rows.mappings().all():
                        changes = {}
                        for column in columns:
                            stored = row[column]
                            if not stored:
                                continue
                            try:
                                if decrypt:
                                    if stored.startswith(PREFIX):
                                        changes[column] = c.decrypt(stored, column)
                                elif c.needs_rewrite(stored):
                                    changes[column] = c.encrypt(c.decrypt(stored, column), column)
                                else:
                                    # The active key id alone doesn't prove the key material
                                    # or the ciphertext is intact: decrypt every value.
                                    c.decrypt(stored, column)
                            except FieldCryptoError:
                                # Ids only, never values. Usually a key removed too early.
                                unreadable.append(f"{table}.{column} id={row['id']}")
                        pending += len(changes)
                        if changes and not check:
                            sets = ", ".join(f"{col} = :{col}" for col in changes)
                            where = "tenant_id = :t AND id = :id"
                            await conn.execute(
                                text(f"UPDATE {table} SET {sets} WHERE {where}"),
                                {**changes, "t": str(tenant_id), "id": row["id"]},
                            )
        if not decrypt:
            pending += await _rewrite_documents(engine, tenants, check=check, errors=unreadable)
            pending += await _rewrite_mfa_seeds(engine, tenants, check=check, errors=unreadable)
    finally:
        await engine.dispose()
    if unreadable:
        # Everything else was handled; these need the key that wrote them put back.
        raise UnreadableValues(unreadable)
    return pending


# Salaries: table -> sealed columns, and the change-history fields that carry an amount.
PAYROLL_COLUMNS: dict[str, tuple[str, ...]] = {"employee_compensations": ("annual_ctc",)}
PAYROLL_LOG_FIELDS = {"employee_compensation": ("annual_ctc", "previous_annual_ctc")}


async def _rewrite_payroll(*, check: bool, decrypt: bool = False) -> int:
    """
    Seal (or, to downgrade, unseal) every salary under the active payroll key. One transaction
    per tenant. The change history is append-only for the app, but this runs as the database
    owner and rewrites only the amount fields of salary entries, never anything else.
    """
    import json

    from hrms.core.field_crypto import FieldCryptoError, payroll_cipher

    if not settings.payroll_encryption_keys and not decrypt:
        if check:
            raise SystemExit("HRMS_PAYROLL_ENCRYPTION_KEYS is not set: nothing is being encrypted")
        print("encrypt-payroll: skipped, HRMS_PAYROLL_ENCRYPTION_KEYS is not set (local)")
        return 0
    c = payroll_cipher()
    engine = create_async_engine(settings.database_url)
    pending = 0
    unreadable: list[str] = []

    def convert(stored: str, column: str) -> str | None:
        """The replacement for `stored`, or None when it is already right."""
        if decrypt:
            return c.decrypt(stored, column) if c.is_sealed(stored) else None
        if c.needs_rewrite(stored):
            return c.encrypt(c.decrypt(stored, column), column)
        c.decrypt(stored, column)  # proves the key material and ciphertext are intact
        return None

    try:
        async with engine.connect() as conn:
            tenants = [r[0] for r in await conn.execute(text("SELECT id FROM tenants ORDER BY id"))]
        for tenant_id in tenants:
            async with engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                for table, columns in PAYROLL_COLUMNS.items():
                    rows = await conn.execute(
                        text(f"SELECT id, {', '.join(columns)} FROM {table} WHERE tenant_id = :t"),
                        {"t": str(tenant_id)},
                    )
                    for row in rows.mappings().all():
                        changes = {}
                        for column in columns:
                            if not row[column]:
                                continue
                            try:
                                new = convert(row[column], column)
                            except FieldCryptoError:
                                unreadable.append(f"{table}.{column} id={row['id']}")
                                continue
                            if new is not None:
                                changes[column] = new
                        pending += len(changes)
                        if changes and not check:
                            sets = ", ".join(f"{col} = :{col}" for col in changes)
                            await conn.execute(
                                text(
                                    f"UPDATE {table} SET {sets} WHERE tenant_id = :t AND id = :id"
                                ),
                                {**changes, "t": str(tenant_id), "id": row["id"]},
                            )
                for entity_type, fields in PAYROLL_LOG_FIELDS.items():
                    rows = await conn.execute(
                        text(
                            "SELECT id, changes FROM entity_change_log "
                            "WHERE tenant_id = :t AND entity_type = :e"
                        ),
                        {"t": str(tenant_id), "e": entity_type},
                    )
                    for row in rows.mappings().all():
                        entry = row["changes"]
                        entry = json.loads(entry) if isinstance(entry, str) else entry
                        touched = False
                        for field in fields:
                            for side in ("old", "new"):
                                value = (entry.get(field) or {}).get(side)
                                if not value:
                                    continue
                                try:
                                    new = convert(str(value), "annual_ctc")
                                except FieldCryptoError:
                                    unreadable.append(f"entity_change_log id={row['id']}")
                                    continue
                                if new is not None:
                                    entry[field][side] = new
                                    touched = True
                                    pending += 1
                        if touched and not check:
                            await conn.execute(
                                text(
                                    "UPDATE entity_change_log SET changes = CAST(:c AS jsonb) "
                                    "WHERE tenant_id = :t AND id = :id"
                                ),
                                {"c": json.dumps(entry), "t": str(tenant_id), "id": row["id"]},
                            )
    finally:
        await engine.dispose()
    if unreadable:
        raise UnreadableValues(unreadable, "HRMS_PAYROLL_ENCRYPTION_KEYS")
    return pending


async def _rewrite_mfa_seeds(engine, tenants, *, check: bool, errors: list[str]) -> int:
    """Retain MFA through encryption-key rotation; seed contents never enter output."""
    from hrms.core.field_crypto import FieldCryptoError, cipher

    c = cipher()
    pending = 0
    for table, tenant_id in [("user_accounts", tid) for tid in tenants] + [
        ("platform_admins", None)
    ]:
        async with engine.begin() as conn:
            params = {}
            where = ""
            if tenant_id is not None:
                params = {"tid": tenant_id}
                where = " WHERE tenant_id=:tid"
                await conn.execute(
                    text("SELECT set_config('app.tenant_id',:t,true)"), {"t": str(tenant_id)}
                )
            rows = await conn.stream(
                text(f"SELECT id,mfa_secret,mfa_pending_secret FROM {table}" + where), params
            )
            async for row in rows.mappings():
                for column in ("mfa_secret", "mfa_pending_secret"):
                    stored = row[column]
                    if not stored:
                        continue
                    try:
                        # Pending/enabled seeds deliberately use the same associated-data
                        # name: confirming enrollment transfers ciphertext atomically.
                        plain = c.decrypt(stored, "mfa_secret")
                        if c.needs_rewrite(stored):
                            pending += 1
                            if not check:
                                await conn.execute(
                                    text(
                                        f"UPDATE {table} SET {column}=:sealed "
                                        "WHERE id=:id"
                                        + (" AND tenant_id=:tid" if tenant_id else "")
                                    ),
                                    {
                                        **params,
                                        "id": row["id"],
                                        "sealed": c.encrypt(plain, "mfa_secret"),
                                    },
                                )
                    except FieldCryptoError:
                        errors.append(f"{table}.{column} id={row['id']}")
            await rows.close()
    return pending


class UnreadableValues(RuntimeError):
    def __init__(self, where: list[str], variable: str = "HRMS_FIELD_ENCRYPTION_KEYS"):
        shown = "; ".join(where[:20]) + (f" (+{len(where) - 20} more)" if len(where) > 20 else "")
        super().__init__(
            f"{len(where)} value(s) don't decrypt with {variable} — add back the "
            f"key that wrote them: {shown}"
        )


async def _rewrite_documents(engine, tenants, *, check: bool, errors: list[str]) -> int:
    """
    Uploaded files: a pre-store file (plain, at a server path) is encrypted into the document
    store and its row repointed; a file sealed with a retired key is re-sealed. Old plain
    files are removed only after their rows are committed.
    """
    from pathlib import Path

    from hrms.core import document_store as store
    from hrms.core.field_crypto import FieldCryptoError, cipher

    active = cipher().active_id
    pending = 0
    for tenant_id in tenants:
        retired: list[str] = []
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            rows = await conn.execute(
                text("SELECT id, storage_path FROM employee_kyc_documents WHERE tenant_id = :t"),
                {"t": str(tenant_id)},
            )
            for doc_id, ref in rows.all():
                if not ref:
                    continue
                if ref.startswith(store.REF_PREFIX):
                    key = ref[len(store.REF_PREFIX) :]
                    try:
                        blob = store.backend().get(key)
                    except store.DocumentMissing:
                        errors.append(f"employee_kyc_documents missing file id={doc_id}")
                        continue
                    try:
                        key_id = store.sealed_key_id(blob)
                    except FieldCryptoError:
                        errors.append(f"employee_kyc_documents malformed file id={doc_id}")
                        continue
                    if key_id == active:
                        try:
                            store.unseal(blob, key)
                        except FieldCryptoError:
                            errors.append(f"employee_kyc_documents corrupt file id={doc_id}")
                        continue
                    pending += 1
                    if not check:
                        try:
                            store.backend().put(key, store.seal(store.unseal(blob, key), key))
                        except FieldCryptoError:
                            errors.append(f"employee_kyc_documents file id={doc_id}")
                    continue
                if not Path(ref).exists():
                    errors.append(f"employee_kyc_documents missing legacy file id={doc_id}")
                    continue
                pending += 1
                if check:
                    continue
                new_ref = store.save(f"kyc/{tenant_id}/{Path(ref).name}", Path(ref).read_bytes())
                await conn.execute(
                    text(
                        "UPDATE employee_kyc_documents SET storage_path = :r "
                        "WHERE tenant_id = :t AND id = :id"
                    ),
                    {"r": new_ref, "t": str(tenant_id), "id": doc_id},
                )
                retired.append(ref)
        for path in retired:
            Path(path).unlink(missing_ok=True)
    return pending


def main(argv: list[str]) -> int:
    if argv == ["migrate"]:
        migrate()
        return 0
    if argv and argv[0] in ("encrypt-pii", "decrypt-pii"):
        check = "--check" in argv[1:]
        try:
            count = asyncio.run(_rewrite_pii(check=check, decrypt=argv[0] == "decrypt-pii"))
        except UnreadableValues as exc:
            print(f"{argv[0]}: {exc}", file=sys.stderr)
            return 1
        if check:
            print(f"{count} identifier value(s) not yet encrypted with the active key")
            return 1 if count else 0
        print(f"{argv[0]}: {count} value(s) rewritten")
        return 0
    if argv and argv[0] in ("encrypt-payroll", "decrypt-payroll"):
        check = "--check" in argv[1:]
        try:
            count = asyncio.run(_rewrite_payroll(check=check, decrypt=argv[0] == "decrypt-payroll"))
        except UnreadableValues as exc:
            print(f"{argv[0]}: {exc}", file=sys.stderr)
            return 1
        if check:
            print(f"{count} salary value(s) not yet encrypted with the active key")
            return 1 if count else 0
        print(f"{argv[0]}: {count} value(s) rewritten")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""
The ERP import scripts, run against an isolated database with synthetic people.

Covers what went wrong the first time: every imported account got a company-wide scope
(so ordinary employees could read the whole company), the "Firstname@1234" accounts were
never forced to change their password, and a re-run overwrote passwords and dates.
"""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.security import hash_password
from tests.helpers import bearer, ok, sign_in, tenant

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mt = _load("migrate_tenants")
fix = _load("fix_imported_scopes")

LEGACY_PASSWORD = "Legacy-pass-1"


# ─── pure: role mapping and helpers (no database) ────────────────────────────


@pytest.mark.parametrize(
    "legacy, role, scope, recognised",
    [
        ("Admin", "SUPER_ADMIN", "ALL", True),
        ("hr", "HR_MANAGER", "LEGAL_ENTITY", True),
        ("Head_of_Department", "MANAGER", "DIRECT_REPORTS", True),
        ("account", "ACCOUNTANT", "LEGAL_ENTITY", True),
        ("User", "EMPLOYEE", "SELF", True),
        ("operation", "EMPLOYEE", "SELF", True),
        ("driver", "EMPLOYEE", "SELF", True),
        ("", "EMPLOYEE", "SELF", True),
        (None, "EMPLOYEE", "SELF", True),
        # Never guessed: unknown roles become plain employees and are reported.
        ("Sales_Admin", "EMPLOYEE", "SELF", False),
        ("administrator", "EMPLOYEE", "SELF", False),
        ("chr", "EMPLOYEE", "SELF", False),
    ],
)
def test_suraj_roles_are_matched_exactly_and_never_over_granted(legacy, role, scope, recognised):
    access, known = mt.map_suraj_role(legacy)
    assert (access.role_name, access.scope_type, known) == (role, scope, recognised)


@pytest.mark.parametrize(
    "role, department, expected",
    [
        ("super_admin", "Management", ("SUPER_ADMIN", "ALL")),
        ("HR_HR Executive", "HR", ("HR_MANAGER", "LEGAL_ENTITY")),
        ("Accounts_Accountant Executive", "Accounts", ("ACCOUNTANT", "LEGAL_ENTITY")),
        ("Moulding_Production Manager", "Production", ("MANAGER", "DIRECT_REPORTS")),
        ("Moulding_Production Supervisor", "Production", ("MANAGER", "DIRECT_REPORTS")),
        ("Moulding_ASST.Prod. MANAGER", "Production", ("MANAGER", "DIRECT_REPORTS")),
        ("Moulding_Helper", "Production", ("EMPLOYEE", "SELF")),
        ("QC_Inspector", "Quality", ("EMPLOYEE", "SELF")),
        # The trap: a housekeeper in the ADMIN department must not become an administrator,
        # and words merely *containing* "hr" must not make anyone HR.
        ("Admin_House Keeping", "Administration", ("EMPLOYEE", "SELF")),
        ("Admin_Housekeeping", "Housekeeping", ("EMPLOYEE", "SELF")),
        ("Shrinkage_Controller", "Stores", ("EMPLOYEE", "SELF")),
        ("Three_Shift_Operator", "Production", ("EMPLOYEE", "SELF")),
    ],
)
def test_sharanga_roles_match_whole_words_only(role, department, expected):
    access = mt.map_rabs_role(role, department)
    assert (access.role_name, access.scope_type) == expected


def test_only_hr_accountants_and_admins_ever_get_more_than_self_or_reports():
    granted = {a.scope_type for a in [*mt.SURAJ_KNOWN_ROLES.values(), mt.SURAJ_EMPLOYEE]}
    assert granted == {"ALL", "LEGAL_ENTITY", "DIRECT_REPORTS", "SELF"}
    for a in [*mt.SURAJ_KNOWN_ROLES.values(), mt.SURAJ_EMPLOYEE]:
        if a.role_name == "EMPLOYEE":
            assert a.scope_type == "SELF"
        if a.role_name == "MANAGER":
            assert a.scope_type == "DIRECT_REPORTS"


def test_initial_password_scheme_and_word_tokens():
    assert mt.initial_password("Amzad") == "Amzad@1234"
    assert mt.initial_password("md. rafi") == "Mdrafi@1234"
    assert mt.initial_password("") == "User@1234"
    assert mt.tokens("HR_HR Executive", None) == {"hr", "executive"}
    assert mt.clean_phone("+91 98765-43210") == "9876543210"
    assert mt.source_id({"_id": {"$oid": "abc"}}) == "abc" and mt.source_id({"_id": None}) is None


def test_bad_legacy_hashes_never_become_usable_passwords():
    good = hash_password(LEGACY_PASSWORD)
    fake_hash = lambda plain: "HASHED:" + plain  # noqa: E731  (avoid bcrypt cost)
    entity = uuid4()
    base = {
        "_id": {"$oid": "1"},
        "username": "u1",
        "first_name": "A",
        "last_name": "B",
        "role": "user",
    }
    ok_rec = mt.build_suraj_record({**base, "password": good}, entity, hash_pw=fake_hash)
    assert ok_rec.password_hash == good and ok_rec.must_change_password is False
    bad = mt.build_suraj_record({**base, "password": "not-bcrypt"}, entity, hash_pw=fake_hash)
    assert bad.password_hash.startswith("HASHED:") and bad.must_change_password is True
    assert bad.password_hash != "HASHED:not-bcrypt"  # a random placeholder, not the legacy value
    assert mt.build_suraj_record({**base, "_id": None}, entity, hash_pw=fake_hash) is None


# ─── database: the importer end to end ───────────────────────────────────────


class Sources:
    """Synthetic source exports whose identifiers are unique to one test (the DB outlives tests)."""

    def __init__(self, folder: Path, domain: str | None = None):
        self.folder = folder
        self.tag = uuid4().hex[:6]
        self.domain = domain or f"{self.tag}.example"
        digits = f"{uuid4().int % 10**6:06d}"
        self._mobile_base = f"91{digits}"
        self.write()

    def code(self, name: str) -> str:
        return f"{name}-{self.tag}"

    def mobile(self, n: int) -> str:
        return f"{self._mobile_base}{n:02d}"

    def write(self):
        good = hash_password(LEGACY_PASSWORD)

        def suraj(oid, username, role, company="Sansar Tradelink", **extra):
            return {
                "_id": {"$oid": f"{oid}-{self.tag}"},
                "company": company,
                "username": self.code(username),
                "first_name": username,
                "last_name": "Test",
                "email": f"{username}@{self.domain}",
                "password": good,
                "role": role,
                "isActive": True,
                "joining_date": "2021-04-01",
                "mobile": None,
                **extra,
            }

        exim = [
            suraj("s1", "admin.one", "Admin"),
            suraj("s2", "hr.one", "hr", company="suraj forwarders private limited"),
            suraj("s3", "boss.one", "Head_of_Department"),
            suraj("s4", "staff.one", "User", mobile=self.mobile(41), pan_no="ABCDE1234F"),
            suraj("s5", "acct.one", "account"),
            suraj("s6", "odd.role", "Sales_Admin"),
            suraj("s7", "staff.one", "User"),  # same username, different source record -> conflict
            suraj("s8", "left.one", "User", isActive=False, deactivatedAt="2024-01-31"),
            suraj("s9", "rabs.one", "User", company="RABS INDUSTRIES INDIA PRIVATE LIMITED"),
            suraj("s10", "ghost.one", "User", company=""),
            suraj("s11", "badhash.one", "User", password="$2b$not-a-real-hash"),
        ]
        logins = [
            {
                "_id": {"$oid": f"r{i}-{self.tag}"},
                "emp_id": self.code(f"RI_00{i}"),
                "username": self.mobile(i),
                "full_name": name,
                "email": "",
                "role": role,
                "is_deleted": deleted,
                **({"deleted_at": "2024-05-05"} if deleted else {}),
            }
            for i, name, role, deleted in (
                (1, "Asha Devi", "super_admin", False),
                (2, "Bela Rao", "Admin_House Keeping", False),
                (3, "Chitra Sen", "Moulding_Production Manager", False),
                (4, "Dev Kumar", "Moulding_Helper", True),
            )
        ]
        profiles = [
            {
                "emp_id": self.code("RI_002"),
                "created_at": "2022-02-02",
                "user_info": {
                    "department": "Administration",
                    "dob": "1990-03-04",
                    "gender": "female",
                    "aadhaar_number": "123412341234",
                    "employees_role": "Contract",
                },
            },
        ]
        (self.folder / "exim.users.json").write_text(json.dumps(exim))
        (self.folder / "Sharanga_Production.login.json").write_text(json.dumps(logins))
        (self.folder / "Sharanga_Production.employee_profiles.json").write_text(
            json.dumps(profiles)
        )


async def _tenant_with(client, *entity_names):
    company = await tenant(client)
    tid = to_uuid(company["user"]["tenant_id"])
    for name in entity_names:
        await ok(
            client, "POST", "/v1/org/legal-entities", json={"name": name, "country_code": "IN"}
        )
    return company, tid


async def _assignment(engine, tid, code):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("""SELECT r.name, ra.scope_type, ra.scope_value, ua.must_change_password
                        FROM user_accounts ua
                        JOIN role_assignments ra
                          ON ra.tenant_id = ua.tenant_id AND ra.user_account_id = ua.id
                        JOIN roles r ON r.tenant_id = ra.tenant_id AND r.id = ra.role_id
                        WHERE ua.tenant_id = :t AND lower(ua.employee_code) = lower(:c)"""),
                {"t": tid, "c": code},
            )
        ).one()


@pytest.mark.database
async def test_importing_suraj_grants_least_privilege_and_survives_bad_records(api, tmp_path):
    client, engine = api
    _, tid = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    src = Sources(tmp_path)

    async with AsyncSession(engine) as session, session.begin():
        stats = await mt.migrate_suraj(session, tid, tmp_path, overwrite=False)

    assert (stats["excluded_rabs"], stats["excluded_blank_company"]) == (1, 1)
    assert stats["created_users"] == 8 and stats["usable"] == 9
    assert [c["source_id"] for c in stats["conflicts"]] == [
        f"s7-{src.tag}"
    ]  # not merged into staff.one
    assert stats["errors"] == []
    assert stats["super_admins"] == [src.code("admin.one")]
    assert stats["unrecognised_legacy_roles"] == {"Sales_Admin": 1}
    assert stats["duplicate_identifiers"]["duplicate_employee_codes"] == 1

    expected = {
        "admin.one": ("SUPER_ADMIN", "ALL"),
        "hr.one": ("HR_MANAGER", "LEGAL_ENTITY"),
        "boss.one": ("MANAGER", "DIRECT_REPORTS"),
        "acct.one": ("ACCOUNTANT", "LEGAL_ENTITY"),
        "staff.one": ("EMPLOYEE", "SELF"),
        "odd.role": ("EMPLOYEE", "SELF"),
        "left.one": ("EMPLOYEE", "SELF"),
    }
    for name, (role, scope) in expected.items():
        got = await _assignment(engine, tid, src.code(name))
        assert (got.name, got.scope_type) == (role, scope), name
    hr_row = await _assignment(engine, tid, src.code("hr.one"))
    assert len(json.loads(hr_row.scope_value)) == 1  # their own company only

    # Legacy passwords keep working, and nobody is forced to change them.
    login = await ok(
        client,
        "POST",
        "/v1/auth/login",
        json={"identifier": src.code("staff.one"), "password": LEGACY_PASSWORD},
    )
    assert login["user"]["must_change_password"] is False and login["user"]["roles"] == ["EMPLOYEE"]
    token = bearer(login["access_token"])
    assert len(await ok(client, "GET", "/v1/employees", headers=token)) == 1  # only themselves
    reports = await ok(client, "GET", "/v1/reports", headers=token)
    employee_report = next(r for r in reports if r["module"] == "EMPLOYEE")
    run = await ok(
        client, "POST", f"/v1/reports/{employee_report['id']}/run", headers=token, json={}
    )
    assert run["total_rows"] == 1
    # A leaver is imported inactive and cannot sign in; a broken legacy hash opens nothing.
    assert (await sign_in(client, src.code("left.one"), LEGACY_PASSWORD)).status_code == 401
    assert (
        await sign_in(client, src.code("badhash.one"), "$2b$not-a-real-hash")
    ).status_code == 401
    assert (await _assignment(engine, tid, src.code("badhash.one"))).must_change_password is True


@pytest.mark.database
async def test_importing_sharanga_forces_password_change_and_reruns_never_undo_users(api, tmp_path):
    client, engine = api
    _, tid = await _tenant_with(client)
    src = Sources(tmp_path)
    ri = lambda n: src.code(f"RI_00{n}")  # noqa: E731

    async with AsyncSession(engine) as session, session.begin():
        first = await mt.migrate_rabs(session, tid, tmp_path, overwrite=False)
    assert first["created_users"] == 4 and first["joined_profiles"] == 1
    assert first["system_accounts"] == 3 and first["super_admins"] == [ri(1)]
    housekeeper = await _assignment(engine, tid, ri(2))
    assert (housekeeper.name, housekeeper.scope_type) == ("EMPLOYEE", "SELF")  # not an admin
    assert (await _assignment(engine, tid, ri(3))).scope_type == "DIRECT_REPORTS"

    # The documented initial password works — and is all it can do until it's replaced.
    login = await ok(
        client,
        "POST",
        "/v1/auth/login",
        json={"identifier": src.mobile(2), "password": "Bela@1234"},
    )
    assert login["user"]["must_change_password"] is True
    forced = bearer(login["access_token"])
    assert (await client.get("/v1/employees", headers=forced)).status_code == 403
    changed = await ok(
        client,
        "POST",
        "/v1/auth/change-password",
        headers=forced,
        json={"current_password": "Bela@1234", "new_password": "Bela-own-secret-9"},
    )
    assert changed["user"]["must_change_password"] is False
    assert (await sign_in(client, ri(2), "Bela@1234")).status_code == 401
    assert (await sign_in(client, ri(2), "Bela-own-secret-9")).status_code == 200
    assert (await sign_in(client, ri(4), "Dev@1234")).status_code == 401  # deleted -> inactive

    # Re-run: nothing new, and — crucially — nothing overwritten.
    async with AsyncSession(engine) as session, session.begin():
        again = await mt.migrate_rabs(session, tid, tmp_path, overwrite=False)
    assert (again["created_users"], again["updated_users"]) == (0, 0)
    assert again["unchanged_users"] == 4
    assert (await sign_in(client, ri(2), "Bela-own-secret-9")).status_code == 200
    assert (await sign_in(client, ri(2), "Bela@1234")).status_code == 401
    # Even --overwrite-existing leaves an account someone has signed in to alone …
    async with AsyncSession(engine) as session, session.begin():
        forced_run = await mt.migrate_rabs(session, tid, tmp_path, overwrite=True)
    assert forced_run["overwrite_skipped_in_use"] >= 1
    assert (await sign_in(client, ri(2), "Bela-own-secret-9")).status_code == 200
    # … while an account nobody has used yet may be corrected before go-live.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE user_accounts SET mobile = '9999999999' "
                "WHERE tenant_id = :t AND employee_code = :c"
            ),
            {"t": tid, "c": ri(3)},
        )
    async with AsyncSession(engine) as session, session.begin():
        await mt.migrate_rabs(session, tid, tmp_path, overwrite=True)
    async with engine.connect() as conn:
        mobile = (
            await conn.execute(
                text(
                    "SELECT mobile FROM user_accounts WHERE tenant_id = :t AND employee_code = :c"
                ),
                {"t": tid, "c": ri(3)},
            )
        ).scalar()
    assert mobile == src.mobile(3)


@pytest.mark.database
async def test_dry_run_changes_nothing_and_a_real_run_asks_first(api, tmp_path, monkeypatch):
    client, engine = api
    _, suraj = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    _, rabs = await _tenant_with(client)
    Sources(tmp_path)

    async def imported():
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM user_accounts WHERE erp_system IS NOT NULL "
                        "AND tenant_id IN (:a, :b)"
                    ),
                    {"a": suraj, "b": rabs},
                )
            ).scalar()

    def args(*extra):
        return [
            "--suraj-tenant",
            str(suraj),
            "--rabs-tenant",
            str(rabs),
            "--data-dir",
            str(tmp_path),
            *extra,
        ]

    assert await mt.main(args("--dry-run")) == 0
    assert await imported() == 0  # a dry run leaves no trace
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert await mt.main(args()) == 1  # declining the prompt aborts
    assert await imported() == 0
    # The Suraj file has a deliberate conflict, so a real run refuses to commit a partial import …
    assert await mt.main(args("--yes")) == 2
    assert await imported() == 0
    # … unless told the rest is wanted.
    assert await mt.main(args("--yes", "--allow-partial")) == 0
    assert await imported() == 12  # 8 Suraj (the conflict is skipped) + 4 Sharanga
    async with engine.connect() as conn:
        batches = (
            await conn.execute(
                text("SELECT count(*) FROM import_batches WHERE tenant_id IN (:a, :b)"),
                {"a": suraj, "b": rabs},
            )
        ).scalar()
    assert batches == 2


async def test_the_target_tenants_must_be_named(tmp_path):
    """Tenant ids differ per environment, so there is no default to fall back on."""
    with pytest.raises(SystemExit) as raised:
        await mt.main(["--dry-run", "--data-dir", str(tmp_path)])
    assert raised.value.code == 2
    with pytest.raises(SystemExit) as raised:  # Sharanga wanted, only the Suraj tenant given
        await mt.main(["--tenant", "rabs", "--suraj-tenant", "suraj", "--dry-run"])
    assert raised.value.code == 2


@pytest.mark.database
async def test_companies_without_a_legal_entity_are_reported_and_block_a_real_run(
    api, tmp_path, caplog
):
    client, engine = api
    _, suraj = await _tenant_with(client)  # the legal entities were never created
    Sources(tmp_path)
    args = ["--tenant", "suraj", "--suraj-tenant", str(suraj), "--data-dir", str(tmp_path)]

    with caplog.at_level("WARNING"):
        async with AsyncSession(engine) as session, session.begin():
            stats = await mt.migrate_suraj(session, suraj, tmp_path, overwrite=False)
            await session.rollback()
    assert stats["usable"] == 0
    assert stats["unmatched_companies"] == {
        "sansar tradelink": 8,
        "suraj forwarders private limited": 1,
    }
    # One line per problem, telling the operator what to create — and no employee usernames.
    assert "Sansar Tradelink" in caplog.text and "Suraj Forwarders Private Limited" in caplog.text
    assert "admin.one" not in caplog.text and "staff.one" not in caplog.text

    # A real run would have imported nothing yet reported success. It refuses instead.
    assert await mt.main([*args, "--yes"]) == 2
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM user_accounts WHERE erp_system IS NOT NULL "
                    "AND tenant_id = :t"
                ),
                {"t": suraj},
            )
        ).scalar()
    assert count == 0


@pytest.mark.database
async def test_the_same_email_in_two_tenants_imports_without_it_instead_of_failing(api, tmp_path):
    client, engine = api
    _, first = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    _, second = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    src = Sources(tmp_path)  # one file, imported into two tenants: identical addresses

    async with AsyncSession(engine) as session, session.begin():
        one = await mt.migrate_suraj(session, first, tmp_path, overwrite=False)
    async with AsyncSession(engine) as session, session.begin():
        two = await mt.migrate_suraj(session, second, tmp_path, overwrite=False)

    assert one["errors"] == [] and one["email_conflicts"] == []
    assert two["errors"] == [] and len(two["email_conflicts"]) == two["created_users"]
    assert two["created_users"] == one["created_users"]  # everyone is still imported
    async with engine.connect() as conn:
        with_email = (
            await conn.execute(
                text(
                    "SELECT count(email) FROM user_accounts "
                    "WHERE tenant_id = :t AND erp_system = 'EXIM'"
                ),
                {"t": second},
            )
        ).scalar()
    assert with_email == 0  # imported without the address, not dropped

    # The same employee code and the same legacy password now exist in two companies:
    # the API asks for the company instead of guessing — and the company code settles it.
    ambiguous = await sign_in(client, src.code("hr.one"), LEGACY_PASSWORD)
    assert ambiguous.status_code == 409 and ambiguous.json()["code"] == "COMPANY_REQUIRED"
    async with engine.connect() as conn:
        slugs = [
            r[0]
            for r in (
                await conn.execute(
                    text("SELECT slug FROM tenants WHERE id IN (:a, :b) ORDER BY created_at"),
                    {"a": first, "b": second},
                )
            ).all()
        ]
    for slug, tid in zip(slugs, (first, second), strict=True):
        r = await client.post(
            "/v1/auth/login",
            json={"identifier": src.code("hr.one"), "password": LEGACY_PASSWORD, "tenant": slug},
        )
        assert r.status_code == 200 and r.json()["user"]["tenant_id"] == to_typed_id("tenant", tid)


# ─── the repair script for accounts imported by the first version ────────────


@pytest.mark.database
async def test_fix_imported_scopes_narrows_only_what_the_old_import_over_granted(api, tmp_path):
    client, engine = api
    _, tid = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    src = Sources(tmp_path)
    async with AsyncSession(engine) as session, session.begin():
        await mt.migrate_suraj(session, tid, tmp_path, overwrite=False)
    _, rabs = await _tenant_with(client)
    async with AsyncSession(engine) as session, session.begin():
        await mt.migrate_rabs(session, rabs, tmp_path, overwrite=False)

    # Recreate what the first import did: every account a company-wide scope, no forced change.
    async with engine.begin() as conn:
        await conn.execute(
            text("""
            UPDATE role_assignments ra SET scope_type = 'LEGAL_ENTITY',
                scope_value = (SELECT to_jsonb(ARRAY[e.legal_entity_id])::text FROM user_accounts ua
                               JOIN employments e
                                 ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
                               WHERE ua.tenant_id = ra.tenant_id AND ua.id = ra.user_account_id)
            WHERE ra.tenant_id IN (:a, :b) AND ra.scope_type IN ('SELF', 'DIRECT_REPORTS')"""),
            {"a": tid, "b": rabs},
        )
        await conn.execute(
            text("UPDATE user_accounts SET must_change_password = false WHERE tenant_id = :t"),
            {"t": rabs},
        )
    # (scope_value there is raw UUIDs; the repair only needs to recognise "their own company".)
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                text("""
            SELECT ra.id, e.legal_entity_id FROM role_assignments ra
            JOIN user_accounts ua ON ua.tenant_id = ra.tenant_id AND ua.id = ra.user_account_id
            JOIN employments e
                                 ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
            WHERE ra.tenant_id IN (:a, :b) AND ra.scope_type = 'LEGAL_ENTITY'"""),
                {"a": tid, "b": rabs},
            )
        ).all()
        for assignment_id, entity in rows:
            await conn.execute(
                text("UPDATE role_assignments SET scope_value = :v WHERE id = :i"),
                {"v": json.dumps([to_typed_id("legal_entity", entity)]), "i": assignment_id},
            )
        # A manager somebody deliberately widened to two companies must be left alone.
        other = (
            await conn.execute(
                text(
                    "SELECT id FROM legal_entities "
                    "WHERE tenant_id = :t AND name = 'Sansar Tradelink'"
                ),
                {"t": tid},
            )
        ).scalar()
        extra = (
            await conn.execute(
                text(
                    "SELECT id FROM legal_entities "
                    "WHERE tenant_id = :t AND name = 'Suraj Forwarders Private Limited'"
                ),
                {"t": tid},
            )
        ).scalar()
        await conn.execute(
            text("""UPDATE role_assignments SET scope_value = :v
            WHERE tenant_id = :t AND user_account_id = (SELECT id FROM user_accounts
                WHERE tenant_id = :t AND employee_code = :c)"""),
            {
                "v": json.dumps(
                    [to_typed_id("legal_entity", other), to_typed_id("legal_entity", extra)]
                ),
                "t": tid,
                "c": src.code("boss.one"),
            },
        )

    async with AsyncSession(engine) as session, session.begin():
        changes = await fix.find_changes(session, str(tid))
        assert {r["who"] for r in changes["to_self"]} >= {
            src.code("staff.one"),
            src.code("odd.role"),
        }
        assert src.code("boss.one") not in {r["who"] for r in changes["to_direct_reports"]}
        assert any(r["who"] == src.code("boss.one") for r, _ in changes["left_alone"])
        assert [r["who"] for r in changes["review_admins"]] == [src.code("admin.one")]
        assert changes["force_password_change"] == []  # only Sharanga accounts are flagged
        await fix.apply(session, changes)

    for name, scope in (
        ("staff.one", "SELF"),
        ("odd.role", "SELF"),
        ("admin.one", "ALL"),
        ("hr.one", "LEGAL_ENTITY"),
        ("boss.one", "LEGAL_ENTITY"),
    ):
        assert (await _assignment(engine, tid, src.code(name))).scope_type == scope, name

    async with AsyncSession(engine) as session, session.begin():
        rabs_changes = await fix.find_changes(session, str(rabs))
        assert len(rabs_changes["force_password_change"]) == 4
        await fix.apply(session, rabs_changes)
        assert (await fix.find_changes(session, str(rabs)))[
            "force_password_change"
        ] == []  # idempotent
    assert (await _assignment(engine, rabs, src.code("RI_001"))).must_change_password is True
    assert (await _assignment(engine, rabs, src.code("RI_003"))).scope_type == "DIRECT_REPORTS"


@pytest.mark.database
async def test_a_rerun_adds_kyc_that_appeared_in_the_source_after_the_first_import(api, tmp_path):
    client, engine = api
    _, tid = await _tenant_with(client, "Sansar Tradelink", "Suraj Forwarders Private Limited")
    src = Sources(tmp_path)
    exim = json.loads((tmp_path / "exim.users.json").read_text())
    for record in exim:
        record.pop("pan_no", None)  # nobody has KYC data yet
    (tmp_path / "exim.users.json").write_text(json.dumps(exim))
    async with AsyncSession(engine) as session, session.begin():
        await mt.migrate_suraj(session, tid, tmp_path, overwrite=False)

    exim = json.loads((tmp_path / "exim.users.json").read_text())
    next(r for r in exim if r["username"] == src.code("staff.one"))["pan_no"] = "ABCDE1234F"
    (tmp_path / "exim.users.json").write_text(json.dumps(exim))
    async with AsyncSession(engine) as session, session.begin():
        again = await mt.migrate_suraj(session, tid, tmp_path, overwrite=False)

    assert again["errors"] == [] and again["updated_users"] == 1  # only the one who gained data
    async with engine.connect() as conn:
        pan = (
            await conn.execute(
                text(
                    """SELECT k.pan_number FROM employee_kyc_records k
               JOIN user_accounts ua
                 ON ua.tenant_id = k.tenant_id AND ua.employment_id = k.employment_id
               WHERE ua.tenant_id = :t AND ua.employee_code = :c"""
                ),
                {"t": tid, "c": src.code("staff.one")},
            )
        ).scalar()
    # Imported identifiers are encrypted at rest like any other (core/field_crypto.py).
    from hrms.core.field_crypto import cipher

    assert pan.startswith("enc:v1:") and cipher().decrypt(pan, "pan_number") == "ABCDE1234F"

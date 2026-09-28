"""Regression coverage for the reviewed access and workflow defects."""

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hrms.core.approvals import require_reviewer
from hrms.core.authn import Principal
from hrms.core.authz import ROLE_PERMISSIONS, Scope, merge_scopes, resolve_scope
from hrms.core.config import Settings
from hrms.model_registry import metadata
from hrms.modules.corrections.schemas import CorrectionCreateRequest
from hrms.modules.kyc.router import _invalidate_verification
from hrms.modules.leave.schemas import LeaveApplyRequest, LeaveTypeUpdate
from hrms.modules.time.service import event_minutes, work_date_for


def grant(role, entities=(), employees=(), all=False):
    return Scope(
        all,
        frozenset(entities),
        frozenset(employees),
        ROLE_PERMISSIONS[role],
        None,
        frozenset({role}),
    )


def test_permission_scopes_do_not_multiply():
    a, b = uuid4(), uuid4()
    scope = merge_scopes([grant("HR_MANAGER", [a]), grant("ACCOUNTANT", [b])], None)
    assert scope.for_permission("people.write").legal_entity_ids == {a}
    assert scope.for_permission("people.read").legal_entity_ids == {a, b}
    assert not scope.for_permission("people.write").covers_entity(b)


def test_mixed_company_and_self_visibility_is_a_union():
    entity, employee = uuid4(), uuid4()
    scope = merge_scopes(
        [grant("ACCOUNTANT", [entity]), grant("EMPLOYEE", employees=[employee])], employee
    )
    clause, params = scope.employment_filter_sql()
    assert " OR " in clause
    assert params["scope_entity_ids"] == [str(entity)]
    assert params["scope_employment_ids"] == [str(employee)]


async def test_department_scope_does_not_expand_to_company(monkeypatch):
    import hrms.core.authz as authz

    department, employee = uuid4(), uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    all=lambda: [
                        {"role_name": "HR_MANAGER", "scope_type": "ORG_UNIT", "scope_value": "[]"}
                    ]
                )
            )
        )
    )
    monkeypatch.setattr(
        authz,
        "_department_scope",
        AsyncMock(return_value=(frozenset({department}), frozenset({employee}))),
    )
    scope = await resolve_scope(session, uuid4(), Principal(uuid4(), uuid4(), None, frozenset()))
    assert not scope.legal_entity_ids
    assert scope.employment_ids == {employee}
    assert scope.org_unit_ids == {department}


@pytest.mark.parametrize(
    "payload",
    [
        {"from_date": "2027-01-04", "to_date": "2027-01-01"},
        {"from_date": "2027-01-04", "to_date": "2027-01-05", "half_day_option": "FIRST_HALF"},
        {"from_date": "2027-01-04", "to_date": "2027-01-04", "half_day_option": "anything"},
    ],
)
def test_invalid_leave_requests(payload):
    with pytest.raises(ValidationError):
        LeaveApplyRequest(leave_type_id="unused", **payload)


def test_patch_cannot_bypass_approval_level_bounds():
    with pytest.raises(ValidationError):
        LeaveTypeUpdate(approval_levels=10)


async def test_self_and_repeat_approval_rejected():
    uid, emp = uuid4(), uuid4()
    principal = Principal(uuid4(), uid, emp, frozenset())
    for target, accounts in [(emp, set()), (uuid4(), {uid})]:
        with pytest.raises(HTTPException):
            await require_reviewer(
                None,
                principal.tenant_id,
                principal,
                grant("MANAGER"),
                target,
                1,
                accounts,
                set(),
                "leave.write",
            )


def test_partial_correction_allowed_but_naive_timestamps_rejected():
    valid = CorrectionCreateRequest(
        work_date=date(2026, 9, 28),
        correction_type="PUNCH_IN",
        requested_punch_in=datetime(2026, 9, 28, 9, tzinfo=UTC),
        reason="Missed punch",
    )
    assert valid.requested_punch_out is None
    with pytest.raises(ValidationError):
        CorrectionCreateRequest(
            work_date=date(2026, 9, 28),
            correction_type="PUNCH_IN",
            requested_punch_in=datetime(2026, 9, 28, 9),
            reason="Missed punch",
        )


def test_explicit_breaks_and_multiple_visits():
    events = [
        SimpleNamespace(punch_type=kind, punched_at=datetime(2026, 9, 28, h, m, tzinfo=UTC))
        for kind, h, m in [
            ("IN", 9, 0),
            ("BREAK_START", 11, 0),
            ("BREAK_END", 11, 30),
            ("OUT", 12, 0),
            ("IN", 13, 0),
            ("OUT", 18, 0),
        ]
    ]
    assert event_minutes(events) == (480, 30, False)


def test_local_midnight_and_overnight_work_date():
    policy = SimpleNamespace(
        timezone="Asia/Kolkata", expected_start_time=time(22), expected_end_time=time(6)
    )
    assert work_date_for(datetime(2026, 9, 29, 0, 30, tzinfo=UTC), policy) == date(2026, 9, 28)
    policy.expected_start_time = time(9)
    policy.expected_end_time = time(18)
    assert work_date_for(datetime(2026, 9, 28, 20, 0, tzinfo=UTC), policy) == date(2026, 9, 29)


def test_kyc_edits_invalidate_reviewer_metadata():
    rec = SimpleNamespace(
        status="VERIFIED",
        verified_by=uuid4(),
        verified_at=datetime.now(UTC),
        rejection_reason=None,
        submitted_at=datetime.now(UTC),
    )
    _invalidate_verification(rec)
    assert rec.status == "DRAFT" and rec.verified_by is None and rec.verified_at is None


def test_complete_model_registration():
    assert {
        "punches",
        "employee_kyc_records",
        "leave_balances",
        "onboarding_items",
        "employee_id_schemes",
        "report_definitions",
    } <= metadata.tables.keys()


def test_production_defaults_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production")

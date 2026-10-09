"""Applicability and source restrictions for migrated EXIM leave types."""

from datetime import timedelta

from fastapi import HTTPException
from sqlmodel import col, select

from hrms.core.datetime_utils import business_today
from hrms.modules.leave.models import LeaveTypeBucketMapping
from hrms.modules.leave.policy_resolver import resolve_employee_bucket_policy


async def validate_legacy_application(session, tenant_id, employment_id, lt, body, days):
    if not lt.legacy_managed:
        return False
    bucket = (
        await session.execute(
            select(LeaveTypeBucketMapping.bucket_id)
            .where(col(LeaveTypeBucketMapping.tenant_id) == tenant_id)
            .where(col(LeaveTypeBucketMapping.leave_type_id) == lt.id)
        )
    ).scalar_one_or_none()
    bp = (
        await resolve_employee_bucket_policy(
            session, tenant_id, employment_id, bucket, body.from_date
        )
        if bucket
        else None
    )
    if bp is None or bp.source_policy is None:
        raise HTTPException(422, "This imported leave policy is not assigned to this employee")
    source = bp.source_policy
    rules = source["rules"]
    if source["status"] != "active":
        raise HTTPException(422, "This imported leave policy is inactive")
    half_day = getattr(body, "half_day_option", "NONE") != "NONE"
    if half_day and not rules.get("half_day_allowed", False):
        raise HTTPException(422, "This leave policy does not allow half days")
    # The old calculator explicitly handles a single half day before the
    # minimum-duration rule. Preserve that case instead of rejecting 0.5 < 1.
    minimum = 0.5 if half_day else rules["min_days_per_application"]
    if days <= 0 or days < minimum:
        raise HTTPException(422, "Leave must cover the minimum number of working days")
    if days > rules["max_days_per_application"]:
        raise HTTPException(422, "Leave exceeds the maximum application duration")
    consecutive = rules.get("max_consecutive_days", 0)
    if consecutive and (body.to_date - body.from_date).days + 1 > consecutive:
        raise HTTPException(422, "Leave exceeds the policy's consecutive-day limit")
    today = business_today()
    if not rules.get("backdated_allowed", False) and body.from_date < today:
        raise HTTPException(422, "This leave policy does not allow backdated applications")
    if body.from_date < today + timedelta(days=rules["advance_notice_days"]):
        raise HTTPException(422, "This leave type requires more advance notice")
    return bool(rules.get("requires_document", False))

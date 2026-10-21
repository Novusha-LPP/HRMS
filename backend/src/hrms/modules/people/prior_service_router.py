"""
Service with an earlier employer (docs/REJOIN_DEVELOPMENT_PLAN.md, R6).

  GET    /v1/persons/{person_id}/prior-service
  POST   /v1/persons/{person_id}/prior-service        (people.write)
  DELETE /v1/persons/{person_id}/prior-service/{id}   (people.write)

A period recognised for leave counts towards the minimum service a leave rule asks for. A period
recognised for gratuity is added to the person's service for gratuity. Periods belong to the
person, so they follow them across employments, and may not overlap time worked here or each other.
"""

from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlmodel import col, select

from hrms.core.authn import CurrentUser
from hrms.core.authz import ScopeDep, require_permission
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id, to_uuid
from hrms.core.tenancy import TenantDep
from hrms.modules.people.models import Employment, PriorService

router = APIRouter(tags=["People"])


class PriorServiceCreate(BaseModel):
    employer_name: str = Field(min_length=1, max_length=200)
    from_date: date
    to_date: date
    recognised_for_leave: bool = False
    recognised_for_gratuity: bool = False
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _order(self):
        if self.to_date < self.from_date:
            raise ValueError("The end date can't be before the start date")
        return self


class PriorServiceResponse(BaseModel):
    id: str
    employer_name: str
    from_date: date
    to_date: date
    months: int
    days: int
    recognised_for_leave: bool
    recognised_for_gratuity: bool
    note: str | None


class PriorServiceSummary(BaseModel):
    items: list[PriorServiceResponse]
    recognised_leave_months: int
    recognised_gratuity_days: int


def whole_months(start: date, end: date) -> int:
    """Complete months between two dates, the way PostgreSQL's age() counts them."""
    months = (end.year - start.year) * 12 + end.month - start.month
    return months - 1 if end.day < start.day else months


def _resp(p: PriorService) -> PriorServiceResponse:
    return PriorServiceResponse(
        id=to_typed_id("prior_service", p.id),
        employer_name=p.employer_name,
        from_date=p.from_date,
        to_date=p.to_date,
        months=whole_months(p.from_date, p.to_date),
        days=(p.to_date - p.from_date).days + 1,
        recognised_for_leave=p.recognised_for_leave,
        recognised_for_gratuity=p.recognised_for_gratuity,
        note=p.note,
    )


async def _authorize_person(session, tenant_id: UUID, scope, person_id: UUID) -> list[Employment]:
    """The person's employments, refusing (404) when the caller can manage none of them."""
    rows = list(
        (
            await session.execute(
                select(Employment)
                .where(col(Employment.tenant_id) == tenant_id)
                .where(col(Employment.person_id) == person_id)
                .where(col(Employment.archived_at).is_(None))
            )
        ).scalars()
    )
    if not any(scope.covers_entity(e.legal_entity_id) for e in rows):
        raise HTTPException(404, "No such person")
    return rows


@router.get(
    "/v1/persons/{person_id}/prior-service",
    response_model=PriorServiceSummary,
    dependencies=[require_permission("people.write")],
)
async def list_prior_service(
    person_id: str, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
) -> PriorServiceSummary:
    scope = scope.for_permission("people.write")
    person = to_uuid(person_id)
    await _authorize_person(session, tenant_id, scope, person)
    rows = list(
        (
            await session.execute(
                select(PriorService)
                .where(col(PriorService.tenant_id) == tenant_id)
                .where(col(PriorService.person_id) == person)
                .order_by(col(PriorService.from_date).desc())
            )
        ).scalars()
    )
    return PriorServiceSummary(
        items=[_resp(p) for p in rows],
        recognised_leave_months=sum(
            whole_months(p.from_date, p.to_date) for p in rows if p.recognised_for_leave
        ),
        recognised_gratuity_days=sum(
            (p.to_date - p.from_date).days + 1 for p in rows if p.recognised_for_gratuity
        ),
    )


@router.post(
    "/v1/persons/{person_id}/prior-service",
    response_model=PriorServiceResponse,
    status_code=201,
    dependencies=[require_permission("people.write")],
)
async def add_prior_service(
    person_id: str,
    body: PriorServiceCreate,
    principal: CurrentUser,
    scope: ScopeDep,
    tenant_id: TenantDep,
    session: SessionDep,
) -> PriorServiceResponse:
    scope = scope.for_permission("people.write")
    person = to_uuid(person_id)
    employments = await _authorize_person(session, tenant_id, scope, person)
    if body.to_date > business_today():
        raise HTTPException(422, "Earlier service has to have ended already")
    for e in employments:
        ended = e.separation_date or business_today()
        if body.from_date <= ended and body.to_date >= e.hire_date:
            raise HTTPException(
                422,
                f"That overlaps their time here ({e.hire_date} to "
                f"{e.separation_date or 'now'}). Earlier service must be from before they "
                "joined or between employments.",
            )
    overlap = (
        await session.execute(
            text(
                "SELECT employer_name FROM prior_service WHERE tenant_id = :t AND person_id = :p "
                "AND from_date <= :to_d AND to_date >= :from_d LIMIT 1"
            ),
            {"t": tenant_id, "p": person, "to_d": body.to_date, "from_d": body.from_date},
        )
    ).first()
    if overlap is not None:
        raise HTTPException(409, f"That overlaps earlier service already recorded ({overlap[0]})")
    row = PriorService(
        tenant_id=tenant_id,
        id=uuid4(),
        person_id=person,
        employer_name=body.employer_name.strip(),
        from_date=body.from_date,
        to_date=body.to_date,
        recognised_for_leave=body.recognised_for_leave,
        recognised_for_gratuity=body.recognised_for_gratuity,
        note=body.note,
        created_by=principal.user_account_id,
    )
    session.add(row)
    await session.flush()
    return _resp(row)


@router.delete(
    "/v1/persons/{person_id}/prior-service/{prior_id}",
    status_code=204,
    dependencies=[require_permission("people.write")],
)
async def delete_prior_service(
    person_id: str, prior_id: str, scope: ScopeDep, tenant_id: TenantDep, session: SessionDep
):
    scope = scope.for_permission("people.write")
    person = to_uuid(person_id)
    await _authorize_person(session, tenant_id, scope, person)
    row = (
        (
            await session.execute(
                select(PriorService)
                .where(col(PriorService.tenant_id) == tenant_id)
                .where(col(PriorService.person_id) == person)
                .where(col(PriorService.id) == to_uuid(prior_id))
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, "No such entry")
    await session.delete(row)
    await session.flush()

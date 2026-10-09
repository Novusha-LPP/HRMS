"""Small, company-wide celebration roster for the signed-in employee's welcome dialog.

This intentionally does not reuse the HR dashboard's permission-scoped people data.
An employee may learn who is celebrating today in their own company, without gaining
access to anyone's birth date, age, contact details, or personnel records.
"""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from hrms.core.authn import CurrentUser
from hrms.core.config import settings
from hrms.core.database import SessionDep
from hrms.core.datetime_utils import business_today
from hrms.core.ids import to_typed_id
from hrms.core.tenancy import TenantDep

router = APIRouter()


class PersonalCelebrations(BaseModel):
    birthday: bool = False
    anniversary_years: int | None = None


class BirthdayCelebrant(BaseModel):
    id: str
    name: str
    company: str
    is_self: bool


class AnniversaryCelebrant(BirthdayCelebrant):
    years: int


class CelebrationsResponse(BaseModel):
    date: date
    timezone: str
    personal: PersonalCelebrations = Field(default_factory=PersonalCelebrations)
    birthdays: list[BirthdayCelebrant] = Field(default_factory=list)
    anniversaries: list[AnniversaryCelebrant] = Field(default_factory=list)


def _celebrates_today(anchor: date | None, today: date) -> bool:
    """February 29 falls on February 28 in a non-leap year, as in upcoming highlights."""
    if anchor is None or anchor > today:
        return False
    try:
        occurrence = anchor.replace(year=today.year)
    except ValueError:
        occurrence = anchor.replace(year=today.year, day=28)
    return occurrence == today


def _anniversary_years(hire_date: date, today: date) -> int | None:
    years = today.year - hire_date.year
    return years if years >= 1 and _celebrates_today(hire_date, today) else None


@router.get(
    "/celebrations", response_model=CelebrationsResponse, summary="Today's company celebrations"
)
async def login_celebrations(
    principal: CurrentUser,
    tenant_id: TenantDep,
    session: SessionDep,
) -> CelebrationsResponse:
    timezone = (
        await session.execute(
            text("SELECT timezone FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one_or_none() or settings.default_timezone
    today = business_today(timezone)
    result = CelebrationsResponse(date=today, timezone=timezone)
    if principal.employment_id is None:
        return result

    # The company is derived from the caller's current employment, never from a selector.
    own = (
        (
            await session.execute(
                text("""
                SELECT e.legal_entity_id, e.person_id, e.hire_date, p.date_of_birth
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                WHERE e.tenant_id = :tid AND e.id = :eid
                  AND e.archived_at IS NULL AND p.archived_at IS NULL
                  AND le.archived_at IS NULL AND le.status = 'ACTIVE'
                  AND e.employment_state IN ('PROBATION', 'ACTIVE', 'NOTICE', 'ON_HOLD')
                  AND e.hire_date <= :today
            """),
                {"tid": tenant_id, "eid": principal.employment_id, "today": today},
            )
        )
        .mappings()
        .first()
    )
    if own is None:
        return result

    result.personal = PersonalCelebrations(
        birthday=_celebrates_today(own["date_of_birth"], today),
        anniversary_years=_anniversary_years(own["hire_date"], today),
    )
    # Filter to today's month/day in SQL; inspect dates only on the server. Including
    # February 29 on the 28th lets the shared recurrence rule decide leap-year behavior.
    month_days = [today.strftime("%m-%d")]
    if today.month == 2 and today.day == 28:
        month_days.append("02-29")
    rows = (
        (
            await session.execute(
                text("""
                SELECT e.id, e.person_id, e.hire_date, p.date_of_birth,
                       trim(COALESCE(NULLIF(p.preferred_name, ''), p.legal_first_name)
                            || ' ' || p.legal_last_name) AS name, le.name AS company
                FROM employments e
                JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
                JOIN legal_entities le ON le.tenant_id = e.tenant_id AND le.id = e.legal_entity_id
                WHERE e.tenant_id = :tid AND e.legal_entity_id = :company_id
                  AND e.archived_at IS NULL AND p.archived_at IS NULL
                  AND le.archived_at IS NULL AND le.status = 'ACTIVE'
                  AND e.employment_state IN ('PROBATION', 'ACTIVE', 'NOTICE', 'ON_HOLD')
                  AND e.hire_date <= :today
                  AND (to_char(p.date_of_birth, 'MM-DD') = ANY(CAST(:month_days AS text[]))
                       OR to_char(e.hire_date, 'MM-DD') = ANY(CAST(:month_days AS text[])))
            """),
                {
                    "tid": tenant_id,
                    "company_id": own["legal_entity_id"],
                    "today": today,
                    "month_days": month_days,
                },
            )
        )
        .mappings()
        .all()
    )

    birthdays: dict[str, BirthdayCelebrant] = {}
    anniversaries = []
    for row in rows:
        if _celebrates_today(row["date_of_birth"], today):
            person_id = to_typed_id("person", row["person_id"])
            birthdays[person_id] = BirthdayCelebrant(
                id=person_id,
                name=row["name"],
                company=row["company"],
                is_self=row["person_id"] == own["person_id"],
            )
        years = _anniversary_years(row["hire_date"], today)
        if years is not None:
            anniversaries.append(
                AnniversaryCelebrant(
                    id=to_typed_id("employment", row["id"]),
                    name=row["name"],
                    company=row["company"],
                    is_self=row["id"] == principal.employment_id,
                    years=years,
                )
            )

    result.birthdays = sorted(
        birthdays.values(),
        key=lambda person: (not person.is_self, person.name.casefold(), person.id),
    )
    result.anniversaries = sorted(
        anniversaries, key=lambda person: (not person.is_self, person.name.casefold(), person.id)
    )
    return result

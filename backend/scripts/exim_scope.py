"""Which EXIM users an import covers (Suraj Group or RABS) and how they link to HRMS employees.

Shared by the punch, leave and regularization history imports so one set of rules decides
whose records are in scope:

  suraj  every user whose company is not RABS, linked through their EXIM account and checked
         against the legal entity of their company;
  rabs   every RABS user, linked through their EXIM account (people created from EXIM) or, for
         people who already exist in HRMS from the Sharanga system, through a reviewer's
         "same person" decision; the tenant has a single legal entity.
"""

import json
from pathlib import Path

from sqlalchemy import text

RABS_COMPANY = "rabs industries india private limited"


def is_rabs_user(user):
    return (user.get("company") or "").strip().casefold() == RABS_COMPANY


def build(company, entities, alias):
    """(entity_for, other_company) for the chosen company."""
    rabs = company == "rabs"
    only = None
    if rabs:
        if len(entities) != 1:
            raise ValueError("The RABS import expects exactly one legal entity in the tenant")
        only = next(iter(entities.values()))

    def entity_for(user):
        if rabs:
            return only
        name = (user.get("company") or "").strip().casefold()
        return entities.get(alias.get(name, name))

    def other_company(user):
        return is_rabs_user(user) != rabs

    return entity_for, other_company


async def decided_links(session, tenant_id, decisions_path):
    """EXIM user id -> link row of the existing employee a reviewer confirmed as the same person."""
    if not decisions_path:
        return {}
    same = json.loads(Path(decisions_path).read_text()).get("same", {})
    rows = (
        (
            await session.execute(
                text("""
        SELECT lower(ua.employee_code) AS code, ua.id AS account_id, ua.employment_id,
               e.legal_entity_id
        FROM user_accounts ua JOIN employments e
          ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        WHERE ua.tenant_id = :tid AND ua.employee_code IS NOT NULL
    """),
                {"tid": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    by_code = {r["code"]: dict(r) for r in rows}
    out = {}
    for exim_id, code in same.items():
        row = by_code.get(str(code).lower())
        if row is not None:
            out[exim_id] = {**row, "erp_user_id": exim_id}
    return out

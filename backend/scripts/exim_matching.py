"""Decide whether an EXIM user is already an HRMS employee, so nobody is created twice.

Shared by the RABS people import and the history imports. Deterministic and conservative: a
person is created only when nothing resembles them. Anything that merely looks similar is
"possible" and is held for a human decision, never created and never silently linked.

Classes returned by classify():
  linked    an HRMS account already carries this EXIM user id (an earlier run, or an adopted one)
  matched   the same person by email, mobile, employee code, or the same name in any word order
  possible  a near match (similar spelling, or shared name parts); needs review
  new       nothing resembles them
"""

import re
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy import text

NEAR_RATIO = 0.84


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))[-10:] or None


def _norm(value):
    value = str(value or "").strip().lower()
    return value or None


def _code(value):
    return re.sub(r"\s+", "", str(value or "").lower()) or None


def tokens(*names):
    words = re.findall(r"[a-z]+", " ".join(str(n or "") for n in names).lower())
    return [w for w in words if len(w) > 1]


def squash(*names):
    return "".join(tokens(*names))


async def load_people(session, tenant_id):
    """Every employee of the tenant with the identifiers and names used for matching."""
    rows = (
        (
            await session.execute(
                text("""
        SELECT ua.employment_id, ua.erp_system, ua.erp_user_id, ua.email, ua.mobile,
               ua.employee_code, p.legal_first_name, p.legal_last_name, p.preferred_name
        FROM user_accounts ua
        JOIN employments e ON e.tenant_id = ua.tenant_id AND e.id = ua.employment_id
        JOIN persons p ON p.tenant_id = e.tenant_id AND p.id = e.person_id
        WHERE ua.tenant_id = :tid
    """),
                {"tid": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


class Index:
    def __init__(self, people):
        self.people = people
        self.by = {k: defaultdict(set) for k in ("email", "mobile", "code", "squash", "tokens")}
        self.linked = {}
        for p in people:
            eid = p["employment_id"]
            if p["erp_system"] == "EXIM" and p["erp_user_id"]:
                self.linked[p["erp_user_id"]] = eid
            if _norm(p["email"]):
                self.by["email"][_norm(p["email"])].add(eid)
            if _digits(p["mobile"]):
                self.by["mobile"][_digits(p["mobile"])].add(eid)
            if _code(p["employee_code"]):
                self.by["code"][_code(p["employee_code"])].add(eid)
            names = (p["legal_first_name"], p["legal_last_name"])
            self.by["squash"][squash(*names)].add(eid)
            self.by["tokens"][tuple(sorted(tokens(*names)))].add(eid)
            p["_squash"] = squash(*names)
            p["_tokens"] = set(tokens(*names, p["preferred_name"]))

    def classify(self, user, exim_id):
        if exim_id in self.linked:
            return "linked", {self.linked[exim_id]}, "EXIM id already linked"
        found, why = set(), []
        for key, values in (
            ("email", [_norm(user.get(k)) for k in ("email", "official_email", "personal_email")]),
            ("mobile", [_digits(user.get("mobile"))]),
            ("code", [_code(user.get("employee_code")), _code(user.get("username"))]),
        ):
            for v in values:
                if v and self.by[key].get(v):
                    found |= self.by[key][v]
                    why.append(key)
        parts = (user.get("first_name"), user.get("middle_name"), user.get("last_name"))
        key_squash = squash(*parts)
        key_tokens = tuple(sorted(tokens(*parts)))
        for table, k in (("squash", key_squash), ("tokens", key_tokens)):
            if k and self.by[table].get(k):
                found |= self.by[table][k]
                why.append("name")
        if len(found) == 1:
            return "matched", found, "+".join(sorted(set(why)))
        if len(found) > 1:
            return "possible", found, "several people share these identifiers"
        # No exact match: look for near names before allowing a new person.
        user_tokens = set(tokens(*parts))
        near = set()
        for p in self.people:
            ratio = SequenceMatcher(None, key_squash, p["_squash"]).ratio() if key_squash else 0
            shared = user_tokens & p["_tokens"]
            first_last = (
                user_tokens
                and p["_tokens"]
                and tokens(user.get("first_name"))[:1] == tokens(p["legal_first_name"])[:1]
                and tokens(user.get("last_name"))[:1] == tokens(p["legal_last_name"])[:1]
            )
            if ratio >= NEAR_RATIO or len(shared) >= 2 or first_last:
                near.add(p["employment_id"])
        if near:
            return "possible", near, "a similar name exists"
        return "new", set(), "no resemblance"

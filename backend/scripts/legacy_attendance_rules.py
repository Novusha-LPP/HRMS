"""Source week-off resolution, matching the old application's PolicyResolver."""


def oid(value):
    return value.get("$oid") if isinstance(value, dict) else value


def resolve_source_weekoff(user, policies):
    active = [p for p in policies if p["status"] == "active"]
    explicit = oid(user.get("weekoff_policy_id"))
    if explicit:
        found = next((p for p in active if oid(p["_id"]) == explicit), None)
        if found:
            return found
        raise ValueError("Explicit source week-off policy is missing or inactive")
    company = oid(user.get("company_id"))
    if not company:
        raise ValueError("Source company is required to resolve week-off defaults")
    candidates = [p for p in active if oid(p.get("company_id")) == company]
    if any(not p["applicability"]["teams"]["all"] for p in candidates):
        raise ValueError("Team-specific week-off resolution requires team exports")
    if len(candidates) > 1:
        raise ValueError("Ambiguous source company week-off default")
    return candidates[0] if candidates else None  # The old resolver defaults to Sundays.


def attendance_policy_name(record):
    return {
        "Operation Weekoff": "Operations Week Off",
        "HO Weekoff": "Head Office Week Off",
        "NOVUSHA WEEKOFF POLICY": "Novusha Week Off",
        "General Week Off": "General Week Off (RABS)",
    }.get(record["policy_name"], record["policy_name"])


SUNDAY_FALLBACK_NAME = "Sunday Week Off (Fallback)"

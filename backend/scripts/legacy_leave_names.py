"""Readable labels shared by imports and the existing-record name correction."""


def company_label(value):
    acronyms = {"iot": "IoT", "llp": "LLP", "sr": "SR", "eximbiz": "EXIMBIZ"}
    return " ".join(acronyms.get(word.casefold(), word.title()) for word in value.split())


def suraj_type_name(kind):
    name = "Privilege Leave" if kind == "privilege" else "Leave Without Pay"
    return f"{name} (Suraj Group)"


def rabs_policy_name(policy):
    name = " ".join(policy["policy_name"].split())
    return name if policy["status"] == "active" else f"{name} (Inactive)"


def definition_name(policy, company):
    return f"{policy['policy_name'].strip()} — {company_label(company)}"[:100]


def assigned_policy_name(company, policies, native_name=None, employment_company=None):
    names = [p["policy_name"].strip() for p in sorted(policies, key=lambda p: p["leave_type"])]
    rules = " + ".join(names) or "No Leave Entitlement"
    if native_name:
        rules += " (Additional Leave)"
    aliases = {"suraj forwarders": "suraj forwarders private limited"}
    source_company = " ".join(company.casefold().split())
    employee_company = " ".join((employment_company or company).casefold().split())
    if aliases.get(source_company, source_company) != employee_company:
        # Preserve the source policy company, but distinguish a set whose linked
        # employees belong to a different HRMS entity. Never silently remap them.
        rules += f" ({company_label(employment_company).split()[0]} Employees)"
    # Reserve space for the rule names rather than truncate them after the company.
    label = company_label(company)
    room = 100 - len(rules) - 3
    if room < 1:
        raise ValueError("Leave policy label exceeds 100 characters")
    if len(label) > room:
        label = label[: room - 1].rstrip() + "…"
    return f"{label} — {rules}"

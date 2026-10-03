"""
The widget catalog for customisable dashboards, and validation of saved layouts.

A widget is a card an HR/admin user can place on their dashboard. Each one declares which
sections of GET /v1/dashboard/hr it reads, so the dashboard computes only what the person's
layout actually shows, and which permissions it needs beyond dashboard.hr, so nobody is
offered a card whose data they can't see (an accountant has no leave access, for example).

The web app keys its components by these ids (frontend/src/components/dashboard/widgets.tsx);
add a widget in both places.
"""

from dataclasses import dataclass

from fastapi import HTTPException

from hrms.core.authz import Scope

# Grid widths, as a share of a 12-column row on a wide screen. Everything is full width
# on a phone.
SIZES = ("quarter", "third", "half", "full")
MAX_WIDGETS = 30

# Sections of the HR dashboard payload (see router.hr_dashboard).
SECTIONS = (
    "headcount",
    "today",
    "actions",
    "pending_requests",
    "upcoming_birthdays",
    "upcoming_anniversaries",
    "department_distribution",
    "entity_distribution",
    "recent_joiners",
    "tenure",
    "kyc",
    "org_summary",
    "trends",
    "exits",
    "attendance_30d",
    "vacancies",
    "statutory",
    "worker_types",
    "leave_by_department",
    "lifecycle",
    "highlights_today",
    "scheduled_changes",
    "action_centre",
)


@dataclass(frozen=True)
class Widget:
    id: str
    title: str
    description: str
    category: str
    default_size: str
    sizes: tuple[str, ...]
    sections: tuple[str, ...] = ()
    # The caller needs at least one of these, on top of dashboard.hr.
    requires_any: tuple[str, ...] = ()

    def available_to(self, scope: Scope) -> bool:
        return not self.requires_any or any(scope.has(p) for p in self.requires_any)

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "default_size": self.default_size,
            "sizes": list(self.sizes),
        }


_KPI = ("quarter", "third", "half")
_CARD = ("third", "half", "full")

CATALOG: tuple[Widget, ...] = (
    Widget("kpi_headcount", "Headcount", "People on the books, and how many joined this month",
           "Overview", "quarter", _KPI, ("headcount",)),
    Widget("kpi_present_today", "Present today", "Who has checked in, as a share of headcount",
           "Attendance", "quarter", _KPI, ("today", "headcount")),
    Widget("kpi_on_leave_today", "On leave today", "Approved leave today, and unplanned absences",
           "Attendance", "quarter", _KPI, ("today",)),
    Widget("kpi_pending_approvals", "Pending approvals",
           "Leave, corrections and personnel actions waiting on a decision",
           "Approvals", "quarter", _KPI, ("actions",)),
    Widget("kpi_open_onboarding", "Onboarding in progress", "New hires still being onboarded",
           "People", "quarter", _KPI, ("actions",), ("onboarding.read",)),
    Widget("kpi_pending_kyc", "KYC to verify", "Submitted KYC records awaiting verification",
           "Compliance", "quarter", _KPI, ("actions",), ("kyc.read",)),
    Widget("attendance_today", "Today's attendance",
           "On time, late, absent and on leave, as a chart", "Attendance", "half", _CARD,
           ("today", "headcount")),
    Widget("approvals_queue", "Needs your decision",
           "The latest leave requests and corrections, approvable from the card",
           "Approvals", "half", ("half", "full"), ("pending_requests",),
           ("leave.approve", "corrections.approve")),
    Widget("leave_activity", "Leave activity",
           "Requests by outcome, and approved days by leave type", "Leave", "full",
           ("half", "full"), (), ("leave.read", "leave.approve")),
    Widget("upcoming_birthdays", "Upcoming birthdays", "Birthdays in the next 45 days",
           "People", "third", _CARD, ("upcoming_birthdays",)),
    Widget("work_anniversaries", "Work anniversaries", "Service milestones in the next 45 days",
           "People", "third", _CARD, ("upcoming_anniversaries",)),
    Widget("new_joiners", "New joiners", "The most recent hires", "People", "third", _CARD,
           ("recent_joiners",)),
    Widget("headcount_by_department", "Headcount by department", "The largest departments",
           "Organisation", "half", _CARD, ("department_distribution",)),
    Widget("headcount_by_company", "Headcount by company", "People in each legal entity",
           "Organisation", "half", _CARD, ("entity_distribution",)),
    Widget("tenure_mix", "Tenure mix", "Average tenure, and people by years of service",
           "People", "third", _CARD, ("tenure",)),
    Widget("kyc_compliance", "KYC compliance", "Verification status across your people",
           "Compliance", "third", _CARD, ("kyc",), ("kyc.read",)),
    Widget("org_overview", "Organisation at a glance",
           "Companies, departments, locations, separations and average tenure",
           "Organisation", "half", _CARD, ("org_summary",)),
    Widget("kpi_new_joiners", "New joiners", "Hires this month, against last month",
           "People", "quarter", _KPI, ("headcount", "trends")),
    Widget("kpi_exits", "Exits", "Separations this month, against last month",
           "People", "quarter", _KPI, ("trends",)),
    Widget("kpi_on_notice", "On notice", "People serving their notice period",
           "People", "quarter", _KPI, ("headcount",)),
    Widget("kpi_avg_attendance", "Avg. attendance",
           "Daily presence over the last 30 days, against the 30 before",
           "Attendance", "quarter", _KPI, ("attendance_30d",)),
    Widget("kpi_vacancies", "Vacancies", "Open seats in positions with a headcount limit",
           "Organisation", "quarter", _KPI, ("vacancies",)),
    Widget("action_centre", "Action centre",
           "Everything waiting on HR, with where to deal with it", "Approvals", "third",
           _CARD, ("action_centre",)),
    Widget("employee_lifecycle", "Employee lifecycle",
           "Probation, notice, and this month's confirmations, promotions and transfers",
           "People", "third", _CARD, ("lifecycle",)),
    Widget("exit_overview", "Exit overview", "Separations over time, notice, and attrition",
           "People", "third", _CARD, ("exits",)),
    Widget("todays_highlights", "Today's highlights",
           "Joining, leaving, birthdays and work anniversaries today", "People", "third",
           _CARD, ("highlights_today",)),
    Widget("scheduled_changes", "Scheduled changes",
           "Transfers, promotions and separations taking effect in the next 30 days",
           "People", "half", _CARD, ("scheduled_changes",)),
    Widget("statutory_ids", "Statutory IDs", "UAN, PF and ESI numbers not yet on file",
           "Compliance", "third", _CARD, ("statutory",), ("kyc.read",)),
    Widget("employee_type", "Employee type", "Permanent, contract and other worker types",
           "Organisation", "third", _CARD, ("worker_types",)),
    Widget("leave_by_department", "Leave by department",
           "Approved leave days in the last 90 days, per person", "Leave", "half", _CARD,
           ("leave_by_department",), ("leave.read", "leave.approve")),
    Widget("quick_actions", "Quick actions", "Shortcuts to everyday HR tasks", "Overview",
           "third", _CARD),
)  # fmt: skip
BY_ID = {w.id: w for w in CATALOG}

# What everyone sees until they customise: the dashboard as it was before customisation.
DEFAULT_LAYOUT = (
    ("kpi_headcount", "quarter"),
    ("kpi_present_today", "quarter"),
    ("kpi_on_leave_today", "quarter"),
    ("kpi_pending_approvals", "quarter"),
    ("attendance_today", "half"),
    ("approvals_queue", "half"),
    ("leave_activity", "full"),
    ("upcoming_birthdays", "third"),
    ("work_anniversaries", "third"),
    ("new_joiners", "third"),
)


# The HRMS overview: fixed-size cards a person can hide, show and reorder. Same storage and
# rules as the widget grid (dashboard="overview"); the web app's HRMSDashboardView renders
# them by these ids.
_FULL = ("full",)
# ruff: noqa: E501 (the catalog reads best one card per line)
OVERVIEW_CATALOG: tuple[Widget, ...] = (
    Widget("attendance", "Attendance overview", "Today's presence", "Attendance", "full", _FULL, ("headcount", "today")),
    Widget("leave", "Leave overview", "Requests by outcome, leave by department", "Leave", "full", _FULL, ("leave_by_department",),
           requires_any=("leave.read", "leave.approve")),
    Widget("action_centre", "Action centre", "What's waiting on HR", "Approvals", "full", _FULL, ("action_centre",)),
    Widget("highlights", "Today's highlights", "Joining, leaving, birthdays, anniversaries", "People", "full", _FULL, ("highlights_today",)),
    Widget("quick_actions", "Quick actions", "Everyday HR shortcuts", "Overview", "full", _FULL),
    Widget("lifecycle", "Employee lifecycle", "Probation, notice, confirmations", "People", "full", _FULL, ("lifecycle",)),
    Widget("training", "Training overview", "Not tracked yet", "People", "full", _FULL),
    Widget("exits", "Exit overview", "Separations and attrition", "People", "full", _FULL, ("exits",)),
    Widget("departments", "Department-wise headcount", "Largest departments", "Organisation", "full", _FULL, ("department_distribution",)),
    Widget("employee_type", "Employee type", "Permanent, contract and more", "Organisation", "full", _FULL, ("worker_types",)),
    Widget("compliance", "Compliance (PF & ESIC)", "Statutory IDs not on file", "Compliance", "full", _FULL, ("statutory",),
           requires_any=("kyc.read",)),
    Widget("tasks", "HR tasks", "Overdue, due soon and upcoming", "Approvals", "full", _FULL, ("action_centre", "scheduled_changes")),
    Widget("recent_joiners", "Recent joiners", "The latest hires", "People", "full", _FULL, ("recent_joiners",)),
    Widget("quick_links", "Quick links", "Instant navigation", "Overview", "full", _FULL),
)  # fmt: skip
CATALOGS = {"hr": CATALOG, "overview": OVERVIEW_CATALOG}
DEFAULTS = {"hr": DEFAULT_LAYOUT, "overview": tuple((w.id, "full") for w in OVERVIEW_CATALOG)}


def _by_id(dashboard: str) -> dict[str, Widget]:
    return {w.id: w for w in CATALOGS[dashboard]}


def available(scope: Scope, dashboard: str = "hr") -> list[Widget]:
    return [w for w in CATALOGS[dashboard] if w.available_to(scope)]


def default_layout(scope: Scope, dashboard: str = "hr") -> list[dict]:
    by_id = _by_id(dashboard)
    return [
        {"widget": wid, "size": size}
        for wid, size in DEFAULTS[dashboard]
        if by_id[wid].available_to(scope)
    ]


def validate(items: list[dict], scope: Scope, dashboard: str = "hr") -> list[dict]:
    """A layout someone is saving: reject anything unknown, unavailable or malformed."""
    if len(items) > MAX_WIDGETS:
        raise HTTPException(422, f"A dashboard holds at most {MAX_WIDGETS} widgets")
    by_id = _by_id(dashboard)
    seen: set[str] = set()
    clean = []
    for item in items:
        widget = by_id.get(item["widget"])
        if widget is None:
            raise HTTPException(422, f"Unknown widget: {item['widget']}")
        if not widget.available_to(scope):
            raise HTTPException(403, f"You don't have access to the {widget.title} widget")
        if item["size"] not in widget.sizes:
            raise HTTPException(
                422, f"{widget.title} can be {', '.join(widget.sizes)}, not {item['size']}"
            )
        if widget.id in seen:
            raise HTTPException(422, f"{widget.title} is on the dashboard twice")
        seen.add(widget.id)
        clean.append({"widget": widget.id, "size": item["size"]})
    return clean


def normalise(saved: list, scope: Scope, dashboard: str = "hr") -> list[dict]:
    """
    A layout read back from storage. Widgets that no longer exist, that the person has lost
    access to, or whose size is no longer offered are dropped or reset quietly — a saved
    dashboard should never fail to load because the catalog or someone's role changed.
    """
    by_id = _by_id(dashboard)
    out, seen = [], set()
    for item in saved if isinstance(saved, list) else []:
        widget = by_id.get(str(item.get("widget"))) if isinstance(item, dict) else None
        if widget is None or widget.id in seen or not widget.available_to(scope):
            continue
        seen.add(widget.id)
        size = item.get("size")
        out.append(
            {"widget": widget.id, "size": size if size in widget.sizes else widget.default_size}
        )
    return out


def sections_for(layout: list[dict], dashboard: str = "hr") -> set[str]:
    by_id = _by_id(dashboard)
    return {s for item in layout for s in by_id[item["widget"]].sections}

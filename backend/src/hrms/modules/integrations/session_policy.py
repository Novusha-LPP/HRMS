"""
What an employee session issued to a connected app may call (plan §8.4).

A token a connected app obtained for an employee (claim "via") works only on these routes, and
only for the features the app's settings switch on. Everything else is refused with
403 NOT_AVAILABLE_VIA_INTEGRATION, even if the employee could reach it by signing in to HRMS.
The endpoints' own permission and scope checks still apply on top: an employee can't approve.

tests/test_integrations_sessions.py checks that every entry matches a real route.
"""

from __future__ import annotations

from starlette.routing import compile_path

# (method, path template) -> features that enable it (any of them). None = always allowed.
SESSION_ROUTES: dict[tuple[str, str], tuple[str, ...] | None] = {
    ("GET", "/v1/auth/me"): None,
    ("POST", "/v1/auth/logout"): None,
    ("GET", "/v1/persons/me"): None,
    ("PATCH", "/v1/persons/me"): ("profile_edit",),
    ("GET", "/v1/dashboard/employee"): None,
    # Attendance
    ("POST", "/v1/time/punches"): ("punch",),
    ("GET", "/v1/time/today"): ("punch", "attendance"),
    ("GET", "/v1/time/attendance-days"): ("attendance",),
    ("GET", "/v1/time/holidays"): ("attendance", "leave"),
    # Corrections
    ("GET", "/v1/corrections"): ("corrections", "approvals"),
    ("POST", "/v1/corrections"): ("corrections",),
    ("POST", "/v1/corrections/{correction_id}/cancel"): ("corrections",),
    ("POST", "/v1/corrections/{correction_id}/approve"): ("approvals",),
    ("POST", "/v1/corrections/{correction_id}/reject"): ("approvals",),
    # Leave
    ("GET", "/v1/leave/types"): ("leave",),
    ("GET", "/v1/leave/balances"): ("leave",),
    ("GET", "/v1/leave/applications"): ("leave", "approvals"),
    ("GET", "/v1/leave/applications/summary"): ("leave",),
    ("POST", "/v1/leave/applications"): ("leave",),
    ("POST", "/v1/leave/applications/{app_id}/submit"): ("leave",),
    ("POST", "/v1/leave/applications/{app_id}/cancel"): ("leave",),
    ("POST", "/v1/leave/applications/{app_id}/approve"): ("approvals",),
    ("POST", "/v1/leave/applications/{app_id}/reject"): ("approvals",),
    ("POST", "/v1/leave/applications/{app_id}/cancel-approve"): ("approvals",),
    ("POST", "/v1/leave/applications/{app_id}/cancel-reject"): ("approvals",),
    # A manager's approvals
    ("GET", "/v1/approvals/inbox"): ("approvals",),
    ("GET", "/v1/approvals/requests/{instance_id}"): ("approvals",),
    ("POST", "/v1/approvals/requests/{instance_id}/decision"): ("approvals",),
    ("GET", "/v1/dashboard/team"): ("approvals",),
    ("GET", "/v1/dashboard/manager"): ("approvals",),
}

# A session issued through an app never carries more than these (plan §6.4).
SESSION_ROLES = frozenset({"EMPLOYEE", "MANAGER"})


_COMPILED = [
    (method, compile_path(template)[0], features)
    for (method, template), features in SESSION_ROUTES.items()
]


def route_features(method: str, path: str) -> tuple[bool, tuple[str, ...] | None]:
    """(listed, features). An unlisted route is never available to an app-issued session."""
    method = method.upper()
    for listed_method, pattern, features in _COMPILED:
        if listed_method == method and pattern.fullmatch(path):
            return True, features
    return False, None

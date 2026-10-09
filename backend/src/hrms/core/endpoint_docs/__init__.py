"""
Per-endpoint reference text for the published API docs, keyed by operationId.

Each entry is (summary, description): the summary is the one-line title shown in the endpoint
list, the description is Markdown for third-party integrators. core/openapi.py applies them
over whatever the route itself declares, so router docstrings can stay as notes for
maintainers. tests/test_openapi_docs.py fails when an endpoint has no entry or an entry no
longer matches an endpoint (operationIds are route function names, so renaming a function
means renaming its key here).
"""

from hrms.core.endpoint_docs import (
    access,
    core_hr,
    insights_platform,
    leave,
    payroll,
    policy,
    time,
    workflows,
)

ENDPOINT_DOCS: dict[str, tuple[str, str]] = {}
for _module in (access, core_hr, payroll, time, policy, leave, workflows, insights_platform):
    _overlap = ENDPOINT_DOCS.keys() & _module.DOCS.keys()
    if _overlap:
        raise RuntimeError(f"Endpoint documented twice: {sorted(_overlap)}")
    ENDPOINT_DOCS.update(_module.DOCS)

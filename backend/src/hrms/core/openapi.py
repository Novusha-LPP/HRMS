"""
The published API contract: the OpenAPI schema and the Swagger UI / ReDoc pages.

Most of the schema comes from the routers themselves. This module adds what FastAPI can't infer:

- an integration guide (the schema's top-level description, shown above the endpoint list);
- a description per tag, plus tag groups for ReDoc's sidebar;
- the security schemes. Routes read their token in a plain dependency (core/authn.py), not
  through FastAPI's security classes, so the schema would otherwise say every endpoint is
  public, and Swagger UI would show no "Authorize" button. Each operation's scheme is worked
  out from its dependency tree, so a new route is labelled correctly without extra work;
- the real error body. Every error, 422 included, uses the envelope from core/error_handlers.py,
  not FastAPI's default HTTPValidationError shape;
- readable operationIds (`create_leave_type`, not `create_leave_type_v1_leave_types_post`),
  so generated clients get sensible method names.

The docs pages follow settings.docs_enabled, as before: off on deployed environments unless
HRMS_API_DOCS_ENABLED says otherwise.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.openapi.docs import get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from hrms.core.authn import get_current_platform_principal, get_current_principal
from hrms.core.endpoint_docs import ENDPOINT_DOCS
from hrms.core.endpoint_docs.examples import REQUEST_EXAMPLES
from hrms.modules.integrations.keys import get_integration_context

TENANT_SCHEME = "TenantBearer"
PLATFORM_SCHEME = "PlatformBearer"
INTEGRATION_KEY_SCHEME = "IntegrationKey"
INTEGRATION_TOKEN_SCHEME = "IntegrationToken"

API_DESCRIPTION = """
The HRMS platform API: core HR, time and attendance, leave, approvals, KYC, recruitment and
reporting for multi-company groups. The web app uses this same API, so anything a user can do
in the app, an integration can do too.

## Quick start

1. **Sign in.** Call `POST /v1/auth/login` with the user's sign-in identifier (email, employee
   code or mobile number) and password:

   ```bash
   curl -X POST "$BASE_URL/v1/auth/login" \\
     -H "Content-Type: application/json" \\
     -d '{"identifier": "hr@example.com", "password": "••••••••"}'
   ```

   The response contains `access_token`, `expires_in` (seconds) and `user`. `user` holds the
   caller's roles, permissions and the companies they can see.

2. **Call the API** with that token in the `Authorization` header:

   ```bash
   curl "$BASE_URL/v1/employees?limit=50" -H "Authorization: Bearer $TOKEN"
   ```

3. **Sign in again when the token expires.** You'll get `401`. There is no refresh token.

**In this page:** run *Auth → Sign in* with **Try it out**, and the token is filled in for every
other request automatically. You can also paste a token into **Authorize** (top right).

## Authentication

| Who | Sign in with | Token works on |
|---|---|---|
| Employees, managers, HR | `POST /v1/auth/login` | all but the two below |
| Connected apps (ERP, CRM) | API key (`X-API-Key`) or OAuth | `/v1/integrations/*` only |
| Platform operators | `POST /v1/platform/login` | `/v1/platform/*` only |

- **Your company is in the token.** The token decides which company's data you see. No header
  or parameter can switch it.
- **Company code.** Some employee codes or mobile numbers are used in more than one company.
  Signing in with one of these returns `409 COMPANY_REQUIRED`. Send the company code as
  `tenant` and try again.
- **Two-factor sign-in.** If the account uses an authenticator app, sign-in returns
  `401 MFA_REQUIRED`. Send the 6-digit code as `otp` and try again.
- **Password change.** A temporary password must be replaced before the API will work.
  Until then, calls return `403 PASSWORD_CHANGE_REQUIRED`. Call `POST /v1/auth/change-password`,
  and use the new token it returns.
- **Changing a password ends every session for that account.** Tokens issued before the
  change stop working at once.
- **Too many failed sign-ins** return `429` with a `Retry-After` header (in seconds).

**For integrations,** connect the system as an app (*Settings → Integrations*) and use its API
key on `/v1/integrations/*`: employee sync, the events feed, read endpoints and employee sessions.
See the *Integrations* section below. Never use a person's own login.

## What a caller can see

What a call returns depends on the caller's roles:

- **Permissions** decide which actions are allowed (for example `leave.write`). Without the
  right permission, a call returns `403` with `Missing permission: <name>`. Where an endpoint
  declares its permission, the endpoint's description says so.
- **Scope** decides which records are visible: all companies, chosen companies, chosen
  departments, the caller's direct reports, or only the caller. List endpoints quietly leave
  out records outside the scope. Single-record endpoints return `403` or `404`.

`GET /v1/auth/me` shows the caller's roles, permissions and visible companies.

## Conventions

- **Base path.** Every endpoint is under `/v1`. New response fields can appear, so your client
  should ignore fields it doesn't recognise.
- **IDs** are opaque strings with a type prefix, for example `emp_…` (employment),
  `per_…` (person), `le_…` (legal entity), `ou_…` (department), `la_…` (leave application).
  Store them and send them back exactly as you got them. Don't parse them.
- **Dates** are `YYYY-MM-DD`, and **timestamps** are ISO 8601. "Today" and work dates follow
  the company's business day, not your clock.
- **Paging.** List endpoints that page take `limit` and `offset`. Each endpoint shows its
  default and maximum `limit`.
- **Request IDs.** Every response has an `X-Request-ID` header. You can send your own
  `X-Request-ID` (up to 64 characters: letters, digits, `.`, `_`, `:`, `-`) and it is used
  instead, which helps you trace a call across both systems.
  Include it when you report a problem.
- **API version.** The `X-App-Version` response header shows the deployed version.

## Errors

Every error has the same JSON body:

```json
{
  "detail": "Validation error on from_date: Input should be a valid date",
  "code": "VALIDATION_ERROR",
  "request_id": "req_01J9...",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Validation error on from_date: Input should be a valid date",
    "details": [
      {"field": "from_date", "message": "Input should be a valid date", "type": "date_parsing"}
    ],
    "request_id": "req_01J9...",
    "timestamp": "2026-10-06T09:30:00+00:00"
  }
}
```

Use `code` in your program logic. `detail` is a message for people and its wording can change.

| Status | Meaning |
|---|---|
| `400` | The request is not valid for the record's current state |
| `401` | Missing, expired or invalid token. Codes: `MFA_REQUIRED`, `MFA_INVALID` |
| `403` | Not allowed. Codes: `PASSWORD_CHANGE_REQUIRED`, `MFA_SETUP_REQUIRED` |
| `404` | Not found, or outside the caller's scope |
| `409` | Conflicts with existing data (`RESOURCE_CONFLICT`, `COMPANY_REQUIRED`) |
| `422` | A field failed validation. `error.details` lists each field |
| `429` | Rate-limited. Wait for the number of seconds in `Retry-After` |
| `5xx` | Server error. Retry with backoff, and quote `request_id` if it continues |

## The schema

The machine-readable OpenAPI 3.1 schema is at [`/openapi.json`](/openapi.json). You can generate
a typed client from it, for example
`npx openapi-typescript $BASE_URL/openapi.json -o hrms-api.d.ts`.
The same reference, as one long page, is at [`/redoc`](/redoc).
"""

# Ordered as they appear in the docs. Every tag a router uses must be listed here — a test
# checks it, so a new module can't ship undocumented.
TAGS_METADATA: list[dict[str, str]] = [
    {
        "name": "Auth",
        "description": "Sign in, sign out, change password, two-factor setup, and the "
        "signed-in user's profile, roles and permissions (`/v1/auth/me`).",
    },
    {
        "name": "Users",
        "description": "User accounts (logins) and the roles that grant permissions and scope.",
    },
    {
        "name": "Preferences",
        "description": "The signed-in user's own settings, such as theme and default dashboard.",
    },
    {
        "name": "Organisation",
        "description": "Company structure: legal entities (companies), locations, departments "
        "(org units), jobs and employee ID schemes. Each has a change history.",
    },
    {
        "name": "People",
        "description": "Persons (the individual) and employments (their job in a company). An "
        "employee is identified by the employment ID (`emp_…`). Personnel actions handle "
        "transfers, promotions and separations, and can be dated in the future.",
    },
    {
        "name": "Onboarding",
        "description": "Checklist templates, and onboarding cases for new hires.",
    },
    {
        "name": "Employee KYC",
        "description": "Identity and bank details, and their documents. Employees maintain "
        "their own (`/me`), and HR verifies them. Every time someone opens a record or document, "
        "it is logged.",
    },
    {
        "name": "Time & Attendance",
        "description": "Punches, daily attendance, overtime review, daily analysis and the "
        "HR attendance register.",
    },
    {
        "name": "Attendance Corrections",
        "description": "Employee requests to fix missed or wrong punches. They go through "
        "the approval workflow.",
    },
    {
        "name": "Holiday calendars",
        "description": "A shared holiday list, and holiday calendars built from it. Calendars "
        "are assigned to companies, departments or individual employees.",
    },
    {
        "name": "HR Policies",
        "description": "Attendance and shift policy templates, their assignments, and the "
        "policy that applies to an employee on a given date.",
    },
    {
        "name": "Leave Management",
        "description": "Leave types, policy sets and buckets, balances, the leave ledger, "
        "applications, and how an application is approved or cancelled. Also covers comp-off, "
        "encashment, accrual runs and year-end close.",
    },
    {
        "name": "Approval workflows",
        "description": "Approval flows, the approver's inbox, decisions and delegations. "
        "Leave, corrections and recruitment openings all use these flows.",
    },
    {
        "name": "Recruitment",
        "description": "Job openings and their approval, the hiring pipeline stages, "
        "candidates and resumes, applications, and turning an application into a hire.",
    },
    {
        "name": "Branding",
        "description": "How payslips (and later letters) look: logo, colours, footer, contact "
        "details and signatories, set once for the group and overridden per company where it "
        "differs. HR and Admin manage it (`org.write`).",
    },
    {
        "name": "Reminders",
        "description": "Scheduled birthday and work-anniversary mail: rules (which event, how many "
        "days ahead, how often, at what time, who is told) and the wording of each mail, with a "
        "preview, a test send, a look at who is coming up, and the delivery log. HR and Admin "
        "manage it (`org.write`).",
    },
    {
        "name": "Payroll",
        "description": "Statutory values (PF, ESIC) with the date they apply from and who "
        "verified them, pay components, versioned salary structures, the CTC breakup, each "
        "employee's salary history, and the payslip templates. Needs the `payroll.*` "
        "permissions, which HR managers don't hold; the Admin grants the payroll roles. "
        "Payslip templates also accept `org.write`.",
    },
    {
        "name": "Dashboard",
        "description": "Dashboards for each role, and each user's saved layout.",
    },
    {
        "name": "Reports",
        "description": "Saved report definitions, the columns and filters each module offers, "
        "and running a report.",
    },
    {
        "name": "Integrations",
        "description": "For connected apps (an ERP, a CRM, a BI tool), with the app's own API key "
        "in `X-API-Key` or a 15-minute token from `/v1/integrations/oauth/token`. Sync "
        "employees in (create, update, exit, rehire, bulk, link), read what changed from the "
        "events feed and the read endpoints, and get a session token so an employee can punch "
        "and see their own data inside the app. Every call is in the app's sync log. A key "
        "only works here, never on the rest of the API.",
    },
    {
        "name": "Integration settings",
        "description": "Settings → Integrations, for the tenant administrator: connected apps, "
        "their keys (shown once), versioned per-company settings with preview and publish "
        "(field ownership, lifecycle, logins, self-service, safety), value mappings, the sync "
        "log, possible duplicates and held exits.",
    },
    {
        "name": "Platform",
        "description": "For platform operators only: tenants, platform admins and the audit "
        "log. These endpoints need a **platform** token from `POST /v1/platform/login`. "
        "A tenant user's token is rejected.",
    },
]

# ReDoc's sidebar groups (Swagger UI ignores this extension).
TAG_GROUPS: list[dict[str, Any]] = [
    {"name": "Access", "tags": ["Auth", "Users", "Preferences"]},
    {
        "name": "Core HR",
        "tags": ["Organisation", "People", "Onboarding", "Employee KYC", "Reminders"],
    },
    {"name": "Pay", "tags": ["Payroll", "Branding"]},
    {
        "name": "Time & leave",
        "tags": [
            "Time & Attendance",
            "Attendance Corrections",
            "Holiday calendars",
            "HR Policies",
            "Leave Management",
        ],
    },
    {"name": "Workflows & hiring", "tags": ["Approval workflows", "Recruitment"]},
    {"name": "Insights", "tags": ["Dashboard", "Reports"]},
    {"name": "Integrations", "tags": ["Integrations", "Integration settings"]},
    {"name": "Platform operations", "tags": ["Platform"]},
]

SWAGGER_UI_PARAMETERS: dict[str, Any] = {
    "docExpansion": "none",  # 219 operations: start collapsed, by tag
    "filter": True,  # search box over tags
    "deepLinking": True,  # shareable #/Tag/operation links
    "persistAuthorization": True,  # keep the token across reloads
    "displayRequestDuration": True,
    "tryItOutEnabled": True,
    "defaultModelsExpandDepth": 0,  # hide the long schema list at the bottom
    "syntaxHighlight": {"theme": "obsidian"},
}

_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "ErrorResponse",
    "description": "The body of every error response. Use `code` in program logic, and show "
    "`detail` to people.",
    "required": ["detail", "code", "request_id", "error"],
    "properties": {
        "detail": {"type": "string", "description": "A message for people."},
        "code": {
            "type": "string",
            "description": "A stable machine-readable code, e.g. `VALIDATION_ERROR`, "
            "`MFA_REQUIRED`, `HTTP_404_NOT_FOUND`.",
        },
        "request_id": {"type": "string", "description": "Same as the X-Request-ID header."},
        "error": {
            "type": "object",
            "required": ["code", "message", "details", "request_id", "timestamp"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {
                    "type": "array",
                    "description": "For validation errors: one entry per field.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "example": "from_date"},
                            "message": {"type": "string"},
                            "type": {"type": "string"},
                        },
                    },
                },
                "request_id": {"type": "string"},
                "timestamp": {"type": "string", "format": "date-time"},
            },
        },
    },
}

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

_COMMON_RESPONSES: dict[str, str] = {
    "401": "Missing, invalid or expired token.",
    "403": "Not allowed: a missing permission, a record outside the caller's scope, or the "
    "account must change its password or set up two-factor sign-in first.",
}

# The browser login flow captures the token from these responses (see _SWAGGER_HTML).
_LOGIN_PATHS = {"/v1/auth/login": TENANT_SCHEME, "/v1/platform/login": PLATFORM_SCHEME}


def _walk(dependant: Dependant):
    yield dependant
    for sub in dependant.dependencies:
        yield from _walk(sub)


def _route_security(route: RouteContext) -> str | None:
    calls = {d.call for d in _walk(route.dependant)}
    if get_integration_context in calls:
        return INTEGRATION_KEY_SCHEME
    if get_current_platform_principal in calls:
        return PLATFORM_SCHEME
    if get_current_principal in calls:
        return TENANT_SCHEME
    return None


# The inner functions of core.authz.require_permission / require_global_permission.
_PERMISSION_DEPS = {
    "require_permission.<locals>._dep": "",
    "require_global_permission.<locals>.dependency": " (all companies)",
}


def _route_permissions(route: RouteContext) -> list[str]:
    """Permissions declared as dependencies on the route or its router, e.g. "`leave.write`"."""
    found: list[str] = []
    for dep in _walk(route.dependant):
        suffix = _PERMISSION_DEPS.get(getattr(dep.call, "__qualname__", ""))
        if suffix is None:
            continue
        for cell in getattr(dep.call, "__closure__", None) or ():
            if isinstance(cell.cell_contents, str):
                label = f"`{cell.cell_contents}`{suffix}"
                if label not in found:
                    found.append(label)
    return found


def _tag_slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary="HR, time, leave and hiring for multi-company groups",
        description=API_DESCRIPTION,
        routes=app.routes,
        tags=TAGS_METADATA,
    )
    schema["x-tagGroups"] = TAG_GROUPS

    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        TENANT_SCHEME: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "The `access_token` from `POST /v1/auth/login`.",
        },
        PLATFORM_SCHEME: {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "The `access_token` from `POST /v1/platform/login`. Only works "
            "on `/v1/platform/*`.",
        },
        INTEGRATION_KEY_SCHEME: {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "A connected app's API key (Settings → Integrations). Only works on "
            "`/v1/integrations/*`.",
        },
        INTEGRATION_TOKEN_SCHEME: {
            "type": "oauth2",
            "description": "OAuth 2.0 client credentials: client_id is the key's public part "
            "(`hrms_<env>_<prefix>`), client_secret is the whole key.",
            "flows": {
                "clientCredentials": {
                    "tokenUrl": "/v1/integrations/oauth/token",
                    "scopes": {},
                }
            },
        },
    }
    schemas = components.setdefault("schemas", {})
    schemas["ErrorResponse"] = _ERROR_SCHEMA

    # Included routers are resolved lazily (FastAPI >= 0.141), so app.routes holds the routers,
    # not their endpoints. iter_route_contexts() yields each endpoint as get_openapi() saw it,
    # with the router's prefix and dependencies applied.
    routes: dict[tuple[str, str], tuple[RouteContext, str]] = {}
    name_counts: dict[str, int] = {}
    for ctx in iter_route_contexts(app.routes):
        original = ctx.original_route
        if not isinstance(original, APIRoute) or not ctx.include_in_schema:
            continue
        name_counts[original.name] = name_counts.get(original.name, 0) + 1
        for method in original.methods or ():
            routes[(ctx.path_format or original.path_format, method.lower())] = (ctx, original.name)

    for path, item in schema.get("paths", {}).items():
        for method, op in item.items():
            found = routes.get((path, method))
            if found is None:
                continue
            route, name = found

            tag = (op.get("tags") or ["api"])[0]
            op["operationId"] = name if name_counts[name] == 1 else f"{_tag_slug(tag)}_{name}"

            responses = op.setdefault("responses", {})
            scheme = _route_security(route)
            if scheme:
                op["security"] = (
                    [{INTEGRATION_KEY_SCHEME: []}, {INTEGRATION_TOKEN_SCHEME: []}]
                    if scheme == INTEGRATION_KEY_SCHEME
                    else [{scheme: []}]
                )
                for code, text in _COMMON_RESPONSES.items():
                    responses.setdefault(
                        code,
                        {
                            "description": text,
                            "content": {"application/json": {"schema": _ERROR_REF}},
                        },
                    )
            else:
                op["security"] = []  # public: sign-in, registration, password reset
            if scheme == INTEGRATION_KEY_SCHEME:
                responses.setdefault(
                    "429",
                    {
                        "description": "Over this key's rate limit. Wait for the number of "
                        "seconds in `Retry-After`.",
                        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
                        "content": {"application/json": {"schema": _ERROR_REF}},
                    },
                )
            if path in _LOGIN_PATHS:
                responses.setdefault(
                    "429",
                    {
                        "description": "Too many failed attempts. Wait for the number of "
                        "seconds in `Retry-After`.",
                        "headers": {"Retry-After": {"schema": {"type": "integer"}}},
                        "content": {"application/json": {"schema": _ERROR_REF}},
                    },
                )
            if "422" in responses:
                responses["422"] = {
                    "description": "Validation error. `error.details` lists each invalid field.",
                    "content": {"application/json": {"schema": _ERROR_REF}},
                }

            documented = ENDPOINT_DOCS.get(op["operationId"])
            if documented:
                op["summary"], op["description"] = documented[0], documented[1].strip()
            example = REQUEST_EXAMPLES.get(op["operationId"])
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if example is not None and body is not None:
                body["example"] = example
            permissions = _route_permissions(route)
            if permissions:
                note = "**Requires permission:** " + ", ".join(permissions)
                op["description"] = (
                    f"{note}\n\n{op['description']}" if op.get("description") else note
                )

    # FastAPI's default validation-error schemas are no longer referenced by anything.
    text = json.dumps(schema)
    for unused in ("HTTPValidationError", "ValidationError"):
        if f"#/components/schemas/{unused}" not in text:
            schemas.pop(unused, None)
    return schema


# Swagger UI, plus one addition: a successful sign-in through "Try it out" authorizes the page
# with the returned token, so nobody has to copy it into the Authorize dialog by hand.
_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<link rel="shortcut icon" href="https://fastapi.tiangolo.com/img/favicon.png">
<style>
  body { margin: 0; }
  .swagger-ui .topbar { display: none; }
  .swagger-ui .info { margin: 32px 0; }
  .swagger-ui .info .description p, .swagger-ui .info .description li { max-width: 72em; }
</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
const LOGIN_PATHS = __LOGIN_PATHS__;
function captureToken(response) {
  try {
    const path = new URL(response.url, window.location.href).pathname;
    const scheme = LOGIN_PATHS[path];
    const token = response.ok && response.body && response.body.access_token;
    if (!scheme || !token) return response;
    // authorizeWithPersistOption honours persistAuthorization (survives a reload);
    // preauthorizeApiKey doesn't.
    const schema = window.ui.specSelectors.securityDefinitions().get(scheme);
    window.ui.authActions.authorizeWithPersistOption(
      {[scheme]: {name: scheme, schema, value: token}});
  } catch (e) { /* never break the response display */ }
  return response;
}
window.ui = SwaggerUIBundle(Object.assign(__PARAMS__, {
  url: "__OPENAPI_URL__",
  dom_id: "#swagger-ui",
  responseInterceptor: captureToken,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
  layout: "BaseLayout",
}));
</script>
</body>
</html>
"""


def _safe_json(value: Any) -> str:
    # Embedded in a <script>: keep "</script>" and friends from closing it early.
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def install_openapi(app: FastAPI, *, docs_enabled: bool) -> None:
    """Use the enriched schema, and serve /docs and /redoc when docs are enabled.

    The app must be created with docs_url=None and redoc_url=None; these pages replace them.
    """
    cache: dict[str, Any] = {}

    def openapi() -> dict[str, Any]:
        if "schema" not in cache:
            cache["schema"] = build_openapi_schema(app)
        return cache["schema"]

    app.openapi = openapi  # type: ignore[method-assign]
    if not docs_enabled:
        return

    title = f"{app.title} — API reference"
    openapi_url = app.openapi_url or "/openapi.json"
    swagger_page = (
        _SWAGGER_HTML.replace("__TITLE__", html.escape(title))
        .replace("__OPENAPI_URL__", openapi_url)
        .replace("__LOGIN_PATHS__", _safe_json(_LOGIN_PATHS))
        .replace("__PARAMS__", _safe_json(SWAGGER_UI_PARAMETERS))
    )

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return HTMLResponse(swagger_page)

    @app.get("/redoc", include_in_schema=False)
    async def redoc() -> HTMLResponse:
        return get_redoc_html(openapi_url=openapi_url, title=title)


if __name__ == "__main__":
    # Write the schema to a file (or stdout), e.g. to hand to a partner while /docs is off:
    #   uv run python -m hrms.core.openapi openapi.json
    import sys

    from hrms.main import app

    out = json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)

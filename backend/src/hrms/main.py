"""
HRMS Platform — FastAPI application entry point.

Multi-tenant: every request must carry a tenant identity (JWT or X-Tenant-ID
header in development).  The tenant ID is propagated into PostgreSQL via
set_config('app.tenant_id', ...) so RLS policies can enforce row-level isolation.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hrms.core.config import settings
from hrms.modules.kernel.auth.router import router as auth_router
from hrms.modules.kernel.users.router import router as users_router
from hrms.modules.org.router import router as org_router
from hrms.modules.platform.router import router as platform_router
from hrms.modules.people.router import router as people_router
from hrms.modules.time.router import router as time_router
from hrms.modules.onboarding.router import router as onboarding_router
from hrms.modules.reports.router import router as reports_router
from hrms.modules.dashboard.router import router as dashboard_router
from hrms.modules.policy.router import router as policy_router
from hrms.modules.leave.router import router as leave_router
from hrms.modules.corrections.router import router as corrections_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Multi-tenant HRMS platform API. "
        "All endpoints require a tenant-scoped access token."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(org_router)
app.include_router(platform_router)
app.include_router(people_router)
app.include_router(time_router)
app.include_router(onboarding_router)
app.include_router(reports_router)
app.include_router(dashboard_router)
app.include_router(policy_router)
app.include_router(leave_router)
app.include_router(corrections_router)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}

"""
HRMS Platform — FastAPI application entry point.

Multi-tenant: every request carries its tenant identity in a signed JWT (there
is no client-supplied tenant header). The tenant ID is propagated into
PostgreSQL via set_config('app.tenant_id', ...) so RLS policies can enforce
row-level isolation.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from hrms import model_registry  # noqa: F401
from hrms.core.config import settings
from hrms.core.database import engine
from hrms.core.error_handlers import register_exception_handlers
from hrms.core.logging import setup_logging
from hrms.core.middleware import RequestLoggingMiddleware
from hrms.core.perf import QueryMetricsMiddleware, instrument_engine
from hrms.modules.corrections.router import router as corrections_router
from hrms.modules.dashboard.router import router as dashboard_router
from hrms.modules.kernel.auth.router import router as auth_router
from hrms.modules.kernel.users.router import router as users_router
from hrms.modules.kyc.router import router as kyc_router
from hrms.modules.leave.router import router as leave_router
from hrms.modules.onboarding.router import router as onboarding_router
from hrms.modules.org.router import router as org_router
from hrms.modules.people.router import router as people_router
from hrms.modules.platform.router import router as platform_router
from hrms.modules.policy.router import router as policy_router
from hrms.modules.reports.router import router as reports_router
from hrms.modules.time.router import router as time_router

# Initialize enterprise logging
setup_logging(log_level=settings.log_level, log_format=settings.log_format)


@asynccontextmanager
async def lifespan(app):
    if settings.environment == "production":
        async with engine.connect() as conn:
            role = (
                await conn.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                )
            ).one()
            if role.rolsuper or role.rolbypassrls:
                raise RuntimeError("Runtime database role must not bypass row-level security")
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Multi-tenant HRMS platform API. All endpoints require a tenant-scoped access token."
    ),
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── Middleware ───────────────────────────────────────────────────────────────
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.query_metrics:
    instrument_engine(engine)
    app.add_middleware(QueryMetricsMiddleware)

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
app.include_router(kyc_router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


# ─── Exception Handlers ───────────────────────────────────────────────────────
register_exception_handlers(app)

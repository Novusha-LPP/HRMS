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
from hrms.core.browser_sessions import BrowserSessionMiddleware
from hrms.core.config import settings
from hrms.core.database import engine
from hrms.core.error_handlers import register_exception_handlers
from hrms.core.error_tracking import init_error_tracking
from hrms.core.health import router as health_router
from hrms.core.logging import setup_logging
from hrms.core.metrics import MetricsMiddleware
from hrms.core.metrics import router as metrics_router
from hrms.core.middleware import RequestLoggingMiddleware
from hrms.core.openapi import install_openapi
from hrms.core.perf import QueryMetricsMiddleware, instrument_engine
from hrms.core.version import APP_VERSION
from hrms.modules.approvals.router import router as approvals_router
from hrms.modules.corrections.router import router as corrections_router
from hrms.modules.dashboard.router import router as dashboard_router
from hrms.modules.integrations.admin import employee_router as integration_employee_router
from hrms.modules.integrations.admin import router as integration_admin_router
from hrms.modules.integrations.router import router as integrations_router
from hrms.modules.kernel.auth.router import router as auth_router
from hrms.modules.kernel.users.router import router as users_router
from hrms.modules.kyc.router import router as kyc_router
from hrms.modules.leave.router import router as leave_router
from hrms.modules.leave.separation_router import router as leave_separation_router
from hrms.modules.onboarding.router import router as onboarding_router
from hrms.modules.org.router import router as org_router
from hrms.modules.payroll.router import router as payroll_router
from hrms.modules.people.rejoin_router import router as rejoin_router
from hrms.modules.people.router import router as people_router
from hrms.modules.platform.router import router as platform_router
from hrms.modules.policy.router import router as policy_router
from hrms.modules.preferences.router import router as preferences_router
from hrms.modules.recruitment.router import router as recruitment_router
from hrms.modules.reports.router import router as reports_router
from hrms.modules.time.holiday_calendars import router as holiday_calendars_router
from hrms.modules.time.register import router as time_register_router
from hrms.modules.time.router import router as time_router

# Initialize enterprise logging
setup_logging(log_level=settings.log_level, log_format=settings.log_format)
init_error_tracking()


@asynccontextmanager
async def lifespan(app):
    if settings.is_deployed:
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
    version=APP_VERSION,
    # Off on deployed environments unless HRMS_API_DOCS_ENABLED says otherwise: the schema is a
    # map of every endpoint, which the public internet doesn't need. /docs and /redoc are served
    # by install_openapi() below, together with the integration guide (core/openapi.py).
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    docs_url=None,
    redoc_url=None,
)

# ─── Middleware ───────────────────────────────────────────────────────────────
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(BrowserSessionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Let the web app read these, so it can show "Reference: req_…" when something fails.
    expose_headers=["X-Request-ID", "X-App-Version", "Content-Disposition"],
)

if settings.query_metrics:
    instrument_engine(engine)
    app.add_middleware(QueryMetricsMiddleware)
if settings.metrics_enabled:
    # Added last, so it's the outermost of these: it times everything below it and starts
    # the statement tally QueryMetricsMiddleware reports from.
    instrument_engine(engine)
    app.add_middleware(MetricsMiddleware)
    app.include_router(metrics_router)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(org_router)
app.include_router(platform_router)
app.include_router(people_router)
app.include_router(rejoin_router)
app.include_router(time_router)
app.include_router(time_register_router)
app.include_router(holiday_calendars_router)
app.include_router(onboarding_router)
app.include_router(reports_router)
app.include_router(dashboard_router)
app.include_router(policy_router)
app.include_router(leave_router)
app.include_router(leave_separation_router)
app.include_router(corrections_router)
app.include_router(approvals_router)
app.include_router(integrations_router)
app.include_router(integration_admin_router)
app.include_router(integration_employee_router)
app.include_router(kyc_router)
app.include_router(preferences_router)
app.include_router(recruitment_router)
app.include_router(payroll_router)


# ─── Health ───────────────────────────────────────────────────────────────────

app.include_router(health_router)


# ─── Exception Handlers ───────────────────────────────────────────────────────
register_exception_handlers(app)


# ─── API docs ─────────────────────────────────────────────────────────────────
install_openapi(app, docs_enabled=settings.docs_enabled)

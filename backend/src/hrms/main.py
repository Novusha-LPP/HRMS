"""
HRMS Platform — FastAPI application entry point.

Multi-tenant: every request carries its tenant identity in a signed JWT (there
is no client-supplied tenant header). The tenant ID is propagated into
PostgreSQL via set_config('app.tenant_id', ...) so RLS policies can enforce
row-level isolation.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hrms import model_registry  # noqa: F401
from hrms.core.config import settings
from hrms.core.database import engine
from hrms.core.errors import CodedHTTPException
from hrms.core.security import PasswordTooLong
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
app.include_router(kyc_router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


logger = logging.getLogger(__name__)


@app.exception_handler(CodedHTTPException)
async def coded_http_exception(request, exc: CodedHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers,
    )


@app.exception_handler(PasswordTooLong)
async def password_too_long(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    # The client only learns "conflict"; the constraint name goes to the log so
    # a 409 can actually be diagnosed (and a NOT NULL/CHECK bug isn't mistaken
    # for a duplicate).
    logger.warning(
        "Integrity violation on %s %s: %s",
        request.method,
        request.url.path,
        getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None) or exc.orig,
    )
    return JSONResponse(
        status_code=409,
        content={
            "detail": "This change conflicts with an existing record or references a missing record"
        },
    )

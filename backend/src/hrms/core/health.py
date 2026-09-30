"""
Health endpoints for load balancers and orchestrators.

  GET /health, /health/live — liveness: the process is up and serving. Never touches the
      database, so a database outage doesn't get every instance restarted.
  GET /health/ready — readiness: send this instance traffic? 200 only when the database
      answers within READY_TIMEOUT_S and holds the schema this code expects. 503 otherwise.

Schema rule: the database's Alembic revision must be this code's head, or *newer* (an
unknown revision). Newer is fine because deployments run migrations before rolling out
code and migrations are expand-then-contract, so old code keeps working on a newer schema
mid-rollout. A known, *older* revision means migrations haven't run: not ready.
"""

import asyncio
import logging
from functools import cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from hrms.core.database import engine
from hrms.core.version import build_info

logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

READY_TIMEOUT_S = 2.0
ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "alembic"


@cache
def _known_revisions() -> tuple[frozenset[str], frozenset[str]] | None:
    """(heads, every revision) of the migrations shipped with this code, or None."""
    if not ALEMBIC_DIR.is_dir():
        return None
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    script = ScriptDirectory.from_config(config)
    return frozenset(script.get_heads()), frozenset(r.revision for r in script.walk_revisions())


@router.get("/health")
@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok", **build_info()}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with asyncio.timeout(READY_TIMEOUT_S), engine.connect() as conn:
            revision = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
        checks["database"] = "ok"
    except Exception as exc:  # any failure to reach the database means "not ready"
        logger.warning("Readiness check: database unavailable (%s)", type(exc).__name__)
        return _result(False, {"database": "unavailable"})

    known = _known_revisions()
    if known is None:
        checks["schema"] = "unchecked"
    elif revision in known[0]:
        checks["schema"] = "ok"
    elif revision in known[1]:
        checks["schema"] = f"migrations pending (database at {revision})"
        return _result(False, checks)
    else:
        checks["schema"] = f"database ahead of code ({revision})"
    return _result(True, checks)


def _result(ok: bool, checks: dict[str, str]) -> JSONResponse:
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "unavailable", "checks": checks, **build_info()},
    )

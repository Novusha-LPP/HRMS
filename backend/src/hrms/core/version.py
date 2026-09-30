"""
What build is running — for /health, the X-App-Version header, logs and error reports.

The version has one source: `version` in backend/pyproject.toml, which release-please bumps
(it keeps frontend/package.json in step). It is read from the installed package's metadata,
so nothing else in the code carries a copy. The commit and build time are baked into the
Docker image as build arguments (see backend/Dockerfile).
"""

import os
from importlib.metadata import PackageNotFoundError, version

try:
    APP_VERSION = version("hrms-platform")
except PackageNotFoundError:  # running from a source tree that was never installed
    APP_VERSION = "0.0.0+unknown"

GIT_SHA = os.environ.get("HRMS_GIT_SHA") or "unknown"
BUILD_TIME = os.environ.get("HRMS_BUILD_TIME") or None


def build_info() -> dict[str, str | None]:
    return {"version": APP_VERSION, "commit": GIT_SHA, "built_at": BUILD_TIME}

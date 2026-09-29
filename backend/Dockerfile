# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    # Outside /app, so mounting ./src over /app/src in docker-compose can't hide the environment.
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN pip install --no-cache-dir uv==0.12.17

WORKDIR /app

# Dependencies come from uv.lock — exactly the versions that were tested — and only the runtime
# ones: no pytest/mypy/testcontainers in the image. This layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
RUN uv sync --frozen --no-dev

ENV PATH="/opt/venv/bin:$PATH"

# Don't run as root. KYC uploads go to /app/storage (a volume in docker-compose).
RUN useradd --system --create-home --uid 10001 hrms \
    && mkdir -p /app/storage \
    && chown -R hrms:hrms /app/storage
USER hrms

EXPOSE 8015
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8015/health', timeout=4).status == 200 else 1)"

# --proxy-headers so request.client is the real caller behind a reverse proxy (login throttling
# counts per client address); only proxies in --forwarded-allow-ips (default: localhost) are trusted.
CMD ["uvicorn", "hrms.main:app", "--host", "0.0.0.0", "--port", "8015", "--proxy-headers"]

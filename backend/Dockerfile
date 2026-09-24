FROM python:3.12-slim

RUN pip install uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

RUN uv pip install --system -e ".[dev]"

EXPOSE 8015

CMD ["uvicorn", "hrms.main:app", "--host", "0.0.0.0", "--port", "8015"]

"""Isolated tests never implicitly connect to a developer's shared database."""

import os

import pytest
from sqlalchemy.engine import make_url

# Maintenance helpers/import scripts and readiness create their own engines rather
# than using the api fixture. Pin their configuration before importing any hrms
# module, so setting only HRMS_TEST_DATABASE_URL cannot reach a shared/default DB.
_test_database_url = os.getenv("HRMS_TEST_DATABASE_URL")
if _test_database_url:
    _test_url = make_url(_test_database_url)
    if not (_test_url.database or "").endswith("_test"):
        raise RuntimeError("Tests require an explicitly isolated *_test database")
    os.environ["HRMS_DATABASE_URL"] = _test_database_url
    os.environ["HRMS_APP_DATABASE_URL"] = _test_url.set(
        username="hrms_app", password="hrms_app_dev_password"
    ).render_as_string(hide_password=False)
    os.environ["HRMS_PLATFORM_DATABASE_URL"] = _test_url.set(
        username="hrms_platform", password="hrms_platform_dev_password"
    ).render_as_string(hide_password=False)


def pytest_addoption(parser):
    parser.addoption(
        "--run-live-demo",
        action="store_true",
        help="Run legacy tests against an explicitly configured demo API",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "live_demo" in item.keywords and not config.getoption("--run-live-demo"):
            item.add_marker(pytest.mark.skip(reason="Legacy demo tests require --run-live-demo"))
        if "database" in item.keywords and not os.getenv("HRMS_TEST_DATABASE_URL"):
            item.add_marker(
                pytest.mark.skip(
                    reason="Set HRMS_TEST_DATABASE_URL to an isolated migrated database"
                )
            )


@pytest.fixture
async def api(monkeypatch, tmp_path):
    """
    An in-process client for the real app plus a superuser engine on the same
    isolated *_test database. The app itself runs as the restricted hrms_app
    role, exactly as in production, so row-level security is in force.
    """
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from hrms.core import database
    from hrms.core.config import settings
    from hrms.main import app

    url = make_url(os.environ["HRMS_TEST_DATABASE_URL"])
    assert url.database.endswith("_test"), "Tests must use an explicitly isolated *_test database"
    admin_engine = create_async_engine(url, poolclass=NullPool)
    runtime = create_async_engine(
        url.set(username="hrms_app", password="hrms_app_dev_password"), poolclass=NullPool
    )
    monkeypatch.setattr(
        database,
        "AsyncSessionLocal",
        async_sessionmaker(runtime, expire_on_commit=False, autoflush=False),
    )
    # The platform console runs as its own restricted role, as in production (migration 0061).
    platform_runtime = create_async_engine(
        url.set(username="hrms_platform", password="hrms_platform_dev_password"),
        poolclass=NullPool,
    )
    monkeypatch.setattr(
        database,
        "PlatformSessionLocal",
        async_sessionmaker(platform_runtime, expire_on_commit=False, autoflush=False),
    )
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    # Encryption at rest on, as in every deployed environment (core/field_crypto.py).
    from hrms.core.field_crypto import DEV_KEYS

    monkeypatch.setattr(settings, "field_encryption_keys", DEV_KEYS)
    # Every test registers its own company from the same address: keep the
    # anonymous-registration limit out of the way (the throttle tests set their
    # own) and start from clean attempt counters.
    monkeypatch.setattr(settings, "register_max_per_hour", 10_000)
    async with admin_engine.begin() as conn:
        await conn.execute(text("DELETE FROM auth_throttle"))
        existing_documents = set((await conn.execute(
            text("SELECT id FROM employee_kyc_documents")
        )).scalars())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, admin_engine
    finally:
        # Each fixture owns a temporary document directory. Remove only the rows it
        # created before that directory disappears; otherwise global encryption audits
        # correctly report dangling references left by earlier tests.
        async with admin_engine.begin() as conn:
            documents = set((await conn.execute(
                text("SELECT id FROM employee_kyc_documents")
            )).scalars()) - existing_documents
            for document_id in documents:
                await conn.execute(text("DELETE FROM employee_kyc_documents WHERE id=:id"),
                                   {"id": document_id})
        await runtime.dispose()
        await platform_runtime.dispose()
        await admin_engine.dispose()

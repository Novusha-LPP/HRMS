"""
local / testing / production (docs/ENVIRONMENTS.md). Testing holds real data, so it is
as strict as production.
"""

import pytest
from pydantic import ValidationError

from hrms.core.config import Settings

DEPLOYED = dict(
    _env_file=None,
    secret_key="x" * 40,
    database_url="postgresql+asyncpg://owner:strong@db/hrms",
    app_database_url="postgresql+asyncpg://hrms_app:strong@db/hrms",
    platform_database_url="postgresql+asyncpg://hrms_platform:strong@db/hrms",
    metrics_token="scrape",
    cors_origins="https://testinghrms.example.com",
    field_encryption_keys="t1:MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    payroll_encryption_keys="p1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
    payroll_pepper="pepper-for-the-tests-0123456789abcdef",
)


def test_local_is_relaxed_and_development_means_local():
    local = Settings(_env_file=None)
    assert local.environment == "local" and not local.is_deployed and local.docs_enabled
    assert Settings(_env_file=None, environment="development").environment == "local"
    Settings(_env_file=None, debug=True)  # fine on a laptop


@pytest.mark.parametrize("environment", ["testing", "production"])
def test_deployed_environments_get_every_safeguard(environment):
    good = Settings(**DEPLOYED, environment=environment)
    assert good.is_deployed and not good.docs_enabled
    for override, message in [
        ({"debug": True}, "Debug mode"),
        ({"secret_key": "change-me-before-production"}, "signing secret"),
        ({"metrics_token": None}, "HRMS_METRICS_TOKEN"),
        ({"cors_origins": "http://testinghrms.example.com"}, "https://"),
        ({"field_encryption_keys": None}, "HRMS_FIELD_ENCRYPTION_KEYS"),
        ({"payroll_encryption_keys": None}, "HRMS_PAYROLL_ENCRYPTION_KEYS"),
        ({"payroll_pepper": None}, "HRMS_PAYROLL_PEPPER"),
        (
            {"app_database_url": "postgresql+asyncpg://hrms_app:hrms_app_dev_password@db/h"},
            "hrms_app",
        ),
        ({"database_url": "postgresql+asyncpg://hrms:hrms@db/h"}, "published development password"),
        ({"platform_database_url": None}, "HRMS_PLATFORM_DATABASE_URL"),
        (
            {
                "platform_database_url": (
                    "postgresql+asyncpg://hrms_platform:hrms_platform_dev_password@db/h"
                )
            },
            "hrms_platform",
        ),
    ]:
        with pytest.raises(ValidationError, match=message):
            Settings(**{**DEPLOYED, **override}, environment=environment)


def test_unknown_environment_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="staging")


def test_docs_can_be_turned_on_deliberately():
    assert Settings(**DEPLOYED, environment="testing", api_docs_enabled=True).docs_enabled


def test_business_today_follows_the_business_not_the_server(monkeypatch):
    from datetime import UTC, date, datetime

    from hrms.core import datetime_utils

    # 20:00 UTC on 31 Jan is 01:30 on 1 Feb in India: a UTC server's date.today() says 31 Jan.
    monkeypatch.setattr(datetime_utils, "now_utc", lambda: datetime(2026, 1, 31, 20, 0, tzinfo=UTC))
    assert datetime_utils.business_today() == date(2026, 2, 1)
    assert datetime_utils.business_today("UTC") == date(2026, 1, 31)

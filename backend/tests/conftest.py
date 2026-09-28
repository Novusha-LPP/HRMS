"""Isolated tests never implicitly connect to a developer's shared database."""

import os

import pytest


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

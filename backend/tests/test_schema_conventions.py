"""
The migrated schema follows docs/database-conventions.md, apart from the known violations
frozen in schema_baseline.txt, and that list only ever shrinks.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hrms.db import conventions, schema_rules

pytestmark = pytest.mark.database

BASELINE = Path(__file__).with_name("schema_baseline.txt")
REGENERATE = "python -m hrms.db.schema_rules --write tests/schema_baseline.txt"


async def _violations() -> list[str]:
    engine = create_async_engine(os.environ["HRMS_TEST_DATABASE_URL"], poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return await schema_rules.collect(conn)
    finally:
        await engine.dispose()


async def test_no_new_schema_violations():
    found = set(await _violations())
    known = set(schema_rules.read_baseline(BASELINE))
    new = sorted(found - known)
    assert not new, (
        "The schema breaks docs/database-conventions.md in ways the baseline doesn't list. "
        "Fix the migration (hrms/db/migration_kit.py has helpers), or record a deliberate "
        "exception with its reason in hrms/db/conventions.py:\n  " + "\n  ".join(new)
    )


async def test_fixed_violations_are_removed_from_the_baseline():
    found = set(await _violations())
    known = set(schema_rules.read_baseline(BASELINE))
    fixed = sorted(known - found)
    assert not fixed, (
        "These baseline entries no longer occur — they were fixed, so delete them from "
        f"tests/schema_baseline.txt (or regenerate it: {REGENERATE}):\n  " + "\n  ".join(fixed)
    )


def test_baseline_is_sorted_and_unique():
    lines = schema_rules.read_baseline(BASELINE)
    assert lines == sorted(set(lines)), f"Keep the baseline sorted and unique ({REGENERATE})"


def test_every_domain_points_at_an_enum():
    for key, path in conventions.DOMAINS.items():
        assert conventions.enum_values(path), f"{key}: {path} has no values"


def test_every_exception_has_a_reason():
    for registry in (
        conventions.SOFT_REFERENCES,
        conventions.UNINDEXED_FK_OK,
        conventions.DOMAIN_EXEMPT,
        conventions.NO_OVERLAP_EXEMPT,
        conventions.ARCHIVE_UNIQUE_INCLUDES_ARCHIVED,
    ):
        for key, reason in registry.items():
            assert reason and reason.strip(), f"{key} needs a reason"


def test_end_semantics_are_declared_once():
    both = conventions.EFFECTIVE_END_EXCLUSIVE & conventions.EFFECTIVE_END_INCLUSIVE
    assert not both, f"declared both inclusive and exclusive: {sorted(both)}"

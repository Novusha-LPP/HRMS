"""docs/architecture/schema.md matches the migrated schema (scripts/schema_diagram.py)."""

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.database

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "schema_diagram.py"


def _load():
    spec = importlib.util.spec_from_file_location("schema_diagram", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_schema_diagram_is_current():
    diagram = _load()
    expected = await diagram.generate(os.environ["HRMS_TEST_DATABASE_URL"])
    assert diagram.OUTPUT.read_text(encoding="utf-8") == expected, (
        "docs/architecture/schema.md is stale: run `python scripts/schema_diagram.py` "
        "against a database migrated to head and commit the result"
    )


def test_every_area_table_exists_once():
    diagram = _load()
    listed = [t for members in diagram.AREAS.values() for t in members]
    assert len(listed) == len(set(listed)), "a table is listed in two areas"

"""
docs/examples/hrms_client.py — the reference client the developer guide points ERP developers to
— run against the real API, so the example can't drift from what the API does.
"""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.helpers import hire, ok, person_and_employment
from tests.integration_support import world

pytestmark = [pytest.mark.database, pytest.mark.serial]

_PATH = Path(__file__).resolve().parents[2] / "docs" / "examples" / "hrms_client.py"
_spec = importlib.util.spec_from_file_location("hrms_reference_client", _PATH)
assert _spec and _spec.loader
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


async def test_the_reference_client_does_what_the_guide_says(api):
    client, _ = api
    w = await world(client)
    hrms = reference.HrmsClient(client, w.key, max_attempts=2)

    created = await hrms.upsert("REF-1", w.new_hire())
    assert created["outcome"] == "CREATED"
    assert (await hrms.upsert("REF-1", {"mobile": "9000000123"}))["outcome"] == "UPDATED"

    # A hire made in HRMS reaches the client's poller, which links it.
    emp = await person_and_employment(client, w.legal_entity, number="REF-HR-1")
    await hire(client, emp["id"], w.placement, when=date.today())
    seen = []

    async def handle(event):
        seen.append(event["event"])
        if event["event"] == "employee.hired" and event["external_id"] is None:
            await hrms.link("REF-2", event["employment_id"])

    cursor = await hrms.poll_once(None, handle)
    assert seen == ["employee.hired"] and cursor.startswith("c_")
    assert await hrms.poll_once(cursor, handle) == cursor  # nothing new

    # Exits are idempotent: the same key on a retry gets the same answer.
    lwd = str(date.today() - timedelta(days=1))
    first = await hrms.exit("REF-1", lwd, idempotency_key="ref-exit-1")
    again = await hrms.exit("REF-1", lwd, idempotency_key="ref-exit-1")
    assert first == again and first["outcome"] == "APPLIED"

    # A session token for an employee works on self-service endpoints.
    token = await hrms.session_for("REF-2")
    me = await ok(client, "GET", "/v1/persons/me", headers={"Authorization": "Bearer " + token})
    assert me["legal_last_name"]

    with pytest.raises(reference.HrmsError) as refused:
        await hrms.upsert("REF-3", w.new_hire(department="Nowhere"))
    assert refused.value.code == "UNKNOWN_DEPARTMENT"
    # The list leaves out people who have left (REF-1 was exited above).
    assert [e["external_id"] for e in await hrms.all_employees()] == ["REF-2"]

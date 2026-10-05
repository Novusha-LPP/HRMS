"""Statutory identifiers are normalised and format-checked by the API, not only the browser."""

import pytest
from pydantic import ValidationError

from hrms.modules.kyc.schemas import KycRecordUpdateRequest
from tests.helpers import employee, ok, tenant


def test_identifiers_are_stored_canonically():
    body = KycRecordUpdateRequest(
        pan_number=" abcde 1234f ",
        aadhaar_number="1234 5678 9012",
        ifsc_code="hdfc-0000123",
        uan_number="1001 2345 6789",
        esi_number="31-00-123456-000-0001",
    )
    assert body.pan_number == "ABCDE1234F"
    assert body.aadhaar_number == "123456789012"
    assert body.ifsc_code == "HDFC0000123"
    assert body.uan_number == "100123456789"
    assert body.esi_number == "31001234560000001"


def test_blank_clears_and_absent_fields_are_untouched():
    body = KycRecordUpdateRequest(pan_number="   ", esi_number=None)
    assert body.model_dump(exclude_unset=True) == {"pan_number": None, "esi_number": None}


@pytest.mark.parametrize(
    "field,value",
    [
        ("aadhaar_number", "1234567890"),  # the browser truncation bug saved exactly this
        ("aadhaar_number", "1234 5678 9012 3"),
        ("pan_number", "ABCDE12345"),
        ("ifsc_code", "HDFCO000123"),  # letter O where the zero belongs
        ("ifsc_code", "NA"),
        ("uan_number", "12345"),
        ("esi_number", "N/A"),
    ],
)
def test_malformed_identifiers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        KycRecordUpdateRequest(**{field: value})


@pytest.mark.database
async def test_api_rejects_malformed_identifier_and_keeps_valid_one(api):
    client, _ = api
    admin = await tenant(client)
    _, login = await employee(client, admin["user"]["legal_entities"][0]["id"])
    headers = {"Authorization": "Bearer " + login["access_token"]}
    saved = await ok(
        client, "PATCH", "/v1/kyc/me", headers=headers, json={"aadhaar_number": "1234 5678 9012"}
    )
    assert saved["aadhaar_number"] == "123456789012"
    bad = await client.patch("/v1/kyc/me", headers=headers, json={"aadhaar_number": "1234567890"})
    assert bad.status_code == 422
    assert "12 digits" in bad.text
    again = await ok(client, "GET", "/v1/kyc/me", headers=headers)
    assert again["aadhaar_number"] == "123456789012"

"""
Sign-in for accounts created by the ERP import: by username / employee ID, by mobile number
(in every format people type it), and by email.

Synthetic people only, in the isolated *_test database. (An earlier version of this file
hard-coded a real-looking mobile number, employee code and password and signed in against
whatever database the environment pointed at.)
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import sign_in
from tests.test_import_scripts import Sources, _tenant_with, mt

pytestmark = pytest.mark.database


async def test_imported_accounts_sign_in_with_username_phone_or_email(api, tmp_path):
    client, engine = api
    _, tid = await _tenant_with(client)
    src = Sources(tmp_path)
    async with AsyncSession(engine) as session, session.begin():
        await mt.migrate_rabs(session, tid, tmp_path, overwrite=False)

    code = src.code("RI_001")  # "Asha Devi" -> initial password Asha@1234
    digits = src.mobile(1)  # ten digits, as imported
    password = "Asha@1234"

    accepted = [
        {"identifier": digits},  # phone, exactly as stored
        {"identifier": f"+91{digits}"},  # with the country code
        {"identifier": f"+91 {digits[:5]} {digits[5:]}"},  # the way people write it
        {"identifier": f"0{digits}"},  # trunk prefix
        {"identifier": code},  # username / employee ID
        {"identifier": code.lower()},  # …in any case
        {"identifier": f"  {code}  "},  # …with stray spaces
        {"email": digits},  # legacy payload shapes
        {"username": code},
        {"phone": f"+91{digits}"},
    ]
    for payload in accepted:
        response = await client.post("/v1/auth/login", json={**payload, "password": password})
        assert response.status_code == 200, (payload, response.text)
        # Every imported Sharanga account starts on its initial password and must replace it.
        assert response.json()["user"]["must_change_password"] is True

    for wrong_identifier in (src.mobile(9), src.code("RI_099"), f"nobody-{uuid4().hex[:6]}"):
        assert (await sign_in(client, wrong_identifier, password)).status_code == 401
    assert (await sign_in(client, code, "not-the-password")).status_code == 401
    assert (await sign_in(client, digits, "not-the-password")).status_code == 401

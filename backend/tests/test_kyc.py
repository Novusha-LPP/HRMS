"""Tests for Employee KYC workflows (both Employee Self-Service and HR Management)."""

import pytest
from httpx import AsyncClient, ASGITransport

from hrms.main import app

DEMO_PASSWORD = "Passw0rd!"


BASE_URL = "http://localhost:8015"


@pytest.mark.asyncio
async def test_kyc_openapi_paths():
    async with AsyncClient(base_url=BASE_URL) as ac:
        res = await ac.get("/openapi.json")
        assert res.status_code == 200
        paths = res.json()["paths"]
        assert "/v1/kyc/me" in paths
        assert "/v1/kyc/me/documents" in paths
        assert "/v1/kyc/me/submit" in paths
        assert "/v1/kyc/summary" in paths
        assert "/v1/kyc/employees" in paths
        assert "/v1/kyc/employees/{employment_id}" in paths
        assert "/v1/kyc/documents/{document_id}/verify" in paths
        assert "/v1/kyc/documents/{document_id}/download" in paths
        assert "/v1/kyc/documents/{document_id}/preview" in paths


@pytest.mark.asyncio
async def test_employee_kyc_self_service():
    async with AsyncClient(base_url=BASE_URL) as ac:
        # 1. Login as Arjun (EMPLOYEE)
        login_res = await ac.post("/v1/auth/login", json={
            "email": "arjun.sharma@sfplgroup.in",
            "password": DEMO_PASSWORD,
        })
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Get own KYC
        me_res = await ac.get("/v1/kyc/me", headers=headers)
        assert me_res.status_code == 200
        data = me_res.json()
        assert data["pan_number"] == "KLMNO9012P"
        assert len(data["documents"]) >= 3
        assert data["completion_percentage"] > 0

        # 3. Update personal KYC details
        patch_res = await ac.patch("/v1/kyc/me", headers=headers, json={
            "emergency_contact_name": "Suresh Sharma Updated",
            "emergency_contact_phone": "+91 98203 99999",
            "blood_group": "B+",
        })
        assert patch_res.status_code == 200
        assert patch_res.json()["emergency_contact_name"] == "Suresh Sharma Updated"

        # 4. Upload a document
        files = {
            "file": ("experience_cert.pdf", b"%PDF-1.4 Mock Experience Certificate", "application/pdf"),
        }
        form_data = {
            "document_type": "EXPERIENCE_LETTER",
            "document_title": "Relieving Letter from Previous Company",
            "document_number": "EXP-2021-098",
        }
        upload_res = await ac.post("/v1/kyc/me/documents", headers=headers, data=form_data, files=files)
        assert upload_res.status_code == 200
        uploaded_doc = upload_res.json()
        assert uploaded_doc["document_type"] == "EXPERIENCE_LETTER"
        assert uploaded_doc["status"] == "PENDING"
        doc_id = uploaded_doc["id"]

        # 5. Preview the uploaded document
        preview_res = await ac.get(f"/v1/kyc/documents/{doc_id}/preview", headers=headers)
        assert preview_res.status_code == 200
        assert b"Mock Experience Certificate" in preview_res.content


@pytest.mark.asyncio
async def test_hr_kyc_management():
    async with AsyncClient(base_url=BASE_URL) as ac:
        # 1. Login as Rahul (HR_MANAGER)
        hr_login = await ac.post("/v1/auth/login", json={
            "email": "rahul.iyer@sfplgroup.in",
            "password": DEMO_PASSWORD,
        })
        assert hr_login.status_code == 200
        hr_token = hr_login.json()["access_token"]
        hr_headers = {"Authorization": f"Bearer {hr_token}"}

        # 2. Get KYC summary stats
        summary_res = await ac.get("/v1/kyc/summary", headers=hr_headers)
        assert summary_res.status_code == 200
        summary = summary_res.json()
        assert summary["total_employees"] > 0
        assert summary["verified_count"] >= 1

        # 3. List employees KYC
        list_res = await ac.get("/v1/kyc/employees", headers=hr_headers)
        assert list_res.status_code == 200
        emp_list = list_res.json()
        assert len(emp_list) > 0

        # Find Arjun's employment
        arjun = next((e for e in emp_list if "Arjun" in e["employee_name"]), None)
        assert arjun is not None
        arjun_emp_id = arjun["employment_id"]

        # 4. View Arjun's full KYC dossier
        dossier_res = await ac.get(f"/v1/kyc/employees/{arjun_emp_id}", headers=hr_headers)
        assert dossier_res.status_code == 200
        dossier = dossier_res.json()
        assert len(dossier["documents"]) >= 3

        # 5. HR verifies one of Arjun's documents
        pending_doc = next((d for d in dossier["documents"] if d["status"] == "PENDING"), None)
        assert pending_doc is not None
        verify_doc_res = await ac.patch(
            f"/v1/kyc/documents/{pending_doc['id']}/verify",
            headers=hr_headers,
            json={"status": "VERIFIED", "comments": "Document verified by HR"},
        )
        assert verify_doc_res.status_code == 200
        assert verify_doc_res.json()["status"] == "VERIFIED"

        # 6. HR uploads a document on Arjun's behalf
        files = {
            "file": ("hr_uploaded_cert.pdf", b"%PDF-1.4 Mock Degree Certificate", "application/pdf"),
        }
        form_data = {
            "document_type": "EDUCATION_CERT",
            "document_title": "B.Tech Degree Certificate (HR Uploaded)",
            "document_number": "DEG-987654",
        }
        hr_upload_res = await ac.post(
            f"/v1/kyc/employees/{arjun_emp_id}/documents",
            headers=hr_headers,
            data=form_data,
            files=files,
        )
        assert hr_upload_res.status_code == 200
        assert hr_upload_res.json()["document_type"] == "EDUCATION_CERT"

        # 7. HR overall verifies Arjun's KYC
        overall_verify_res = await ac.post(
            f"/v1/kyc/employees/{arjun_emp_id}/verify",
            headers=hr_headers,
            json={"status": "VERIFIED"},
        )
        assert overall_verify_res.status_code == 200
        assert overall_verify_res.json()["status"] == "VERIFIED"

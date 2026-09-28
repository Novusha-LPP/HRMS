"""Tests for Daily Employee Analysis endpoint."""

import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.live_demo

DEMO_PASSWORD = "Passw0rd!"
BASE_URL = os.environ.get("HRMS_DEMO_API_URL", "http://localhost:8015")


@pytest.mark.asyncio
async def test_daily_analysis_endpoint():
    async with AsyncClient(base_url=BASE_URL) as ac:
        # 1. Login as HR Manager
        login_res = await ac.post(
            "/v1/auth/login",
            json={
                "email": "rahul.iyer@sfplgroup.in",
                "password": DEMO_PASSWORD,
            },
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Query daily-analysis
        res = await ac.get("/v1/time/daily-analysis", headers=headers)
        assert res.status_code == 200, f"daily-analysis failed: {res.text}"
        data = res.json()

        assert "work_date" in data
        assert "metrics" in data
        assert "department_stats" in data
        assert "hourly_arrivals" in data
        assert "employees" in data

        metrics = data["metrics"]
        assert "total_headcount" in metrics
        assert "presence_rate" in metrics
        assert len(data["employees"]) > 0

        # 3. Test filtering by search query
        first_emp = data["employees"][0]
        search_res = await ac.get(
            f"/v1/time/daily-analysis?search={first_emp['name'][:4]}", headers=headers
        )
        assert search_res.status_code == 200
        search_data = search_res.json()
        assert len(search_data["employees"]) >= 1

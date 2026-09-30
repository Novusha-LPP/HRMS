"""
Concurrent load against a running API — the realistic mix of a working day.

    PERF_PERSONAS=perf/out/perf-2k.json locust -f perf/locustfile.py --host http://127.0.0.1:8099

Scenarios (weights ≈ a 2,000-person company's traffic):
  * MorningRush  — log in, punch IN, check today (the 09:00–09:30 spike; bcrypt-bound)
  * Employee     — self-service browsing: dashboard, balances, own leave, own attendance
  * Manager      — team dashboard, pending approvals
  * HR           — HR dashboard, employee list, daily analysis, all leave applications

Employee logins are the seeded e000001…eNNNNNN accounts; managers and HR use the personas.
Each simulated user logs in once and reuses its token, like the SPA.
"""

import itertools
import json
import os
import random
from datetime import date, timedelta
from pathlib import Path

from locust import HttpUser, between, task

PASSWORD = "PerfPassw0rd!"
META = json.loads(Path(os.environ["PERF_PERSONAS"]).read_text())
SLUG = META["slug"]
EMPLOYEES = META["employees"]
TODAY = date.today()
_next_employee = itertools.count(1)


def employee_email() -> str:
    # Skip the last 3 (HR personas) so employees stay plain self-service users.
    n = (next(_next_employee) - 1) % (EMPLOYEES - 3) + 1
    return f"e{n:06d}@{SLUG}.perf.invalid"


class _Authed(HttpUser):
    abstract = True
    email: str = ""

    def login(self, email: str) -> None:
        r = self.client.post(
            "/v1/auth/login",
            json={"identifier": email, "password": PASSWORD},
            name="POST /v1/auth/login",
        )
        self.headers = {"Authorization": f"Bearer {r.json().get('access_token', '')}"}

    def get(self, url: str, name: str | None = None):
        return self.client.get(url, headers=self.headers, name=name or url.split("?")[0])


class MorningRush(_Authed):
    weight = 3
    wait_time = between(1, 3)

    @task
    def arrive(self) -> None:
        self.login(employee_email())
        self.client.post(
            "/v1/time/punches",
            headers=self.headers,
            json={"punch_type": "IN"},
            name="POST /v1/time/punches",
        )
        self.get("/v1/time/today")
        self.get("/v1/dashboard/employee")


class Employee(_Authed):
    weight = 10
    wait_time = between(2, 6)

    def on_start(self) -> None:
        self.login(employee_email())

    @task(3)
    def dashboard(self) -> None:
        self.get("/v1/dashboard/employee")

    @task(2)
    def balances(self) -> None:
        self.get("/v1/leave/balances")

    @task(2)
    def my_leave(self) -> None:
        self.get("/v1/leave/applications", name="/v1/leave/applications (self)")

    @task(2)
    def my_attendance(self) -> None:
        self.get(
            f"/v1/time/attendance-days?from_date={TODAY - timedelta(days=30)}&to_date={TODAY}",
            name="/v1/time/attendance-days (self)",
        )

    @task(1)
    def today(self) -> None:
        self.get("/v1/time/today")


class Manager(_Authed):
    weight = 2
    wait_time = between(3, 8)

    def on_start(self) -> None:
        self.login(META["personas"][random.choice(["team_lead", "dept_head"])])

    @task(3)
    def dashboard(self) -> None:
        self.get("/v1/dashboard/manager")

    @task(2)
    def pending(self) -> None:
        self.get(
            "/v1/leave/applications?status=PENDING_L1", name="/v1/leave/applications (pending)"
        )


class HR(_Authed):
    weight = 1
    wait_time = between(3, 8)

    def on_start(self) -> None:
        self.login(META["personas"][random.choice(["hr_all", "hr_entity", "hr_dept"])])

    @task(3)
    def dashboard(self) -> None:
        self.get("/v1/dashboard/hr")

    @task(2)
    def employees(self) -> None:
        self.get(
            "/v1/employees?limit=50&offset=" + str(random.randrange(0, 1500, 50)),
            name="/v1/employees",
        )

    @task(2)
    def daily(self) -> None:
        self.get(f"/v1/time/daily-analysis?work_date={TODAY - timedelta(days=1)}")

    @task(1)
    def all_leave(self) -> None:
        self.get("/v1/leave/applications", name="/v1/leave/applications (all)")

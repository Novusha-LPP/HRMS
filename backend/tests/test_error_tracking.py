"""What core/error_tracking actually sends to Sentry — captured, never sent anywhere."""

import pytest
import sentry_sdk
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sentry_sdk.transport import Transport

from hrms.core.error_handlers import register_exception_handlers
from hrms.core.error_tracking import init_error_tracking
from hrms.core.middleware import RequestLoggingMiddleware
from hrms.core.version import APP_VERSION


class CapturingTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def captured():
    transport = CapturingTransport()
    assert init_error_tracking(dsn="https://public@o0.ingest.sentry.io/0", transport=transport)
    yield transport
    sentry_sdk.get_client().close()


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    @app.post("/boom")
    async def boom():
        # Built at runtime so the value is data, not a literal in the source context Sentry
        # sends alongside each stack frame.
        pan = "ABCDE" + "1234F"
        employee = {"pan": pan}  # a local variable that must not be sent
        raise ValueError(f"could not verify PAN {pan} for {len(employee)} employee")

    return app


def test_disabled_without_a_dsn():
    assert init_error_tracking(dsn=None) is False


async def test_errors_are_sent_tagged_and_scrubbed(captured):
    async with AsyncClient(
        transport=ASGITransport(app=_app(), raise_app_exceptions=False), base_url="http://t"
    ) as client:
        response = await client.post(
            "/boom?pan=" + "ABCDE" + "1234F",
            headers={"Authorization": "Bearer secret-token"},
            json={"aadhaar": "2345 6789 0123", "salary": 90000},
        )
    sentry_sdk.flush()
    assert response.status_code == 500

    [event] = captured.events  # one event, not one per logger that saw the failure
    raw = str(event)
    for secret in ("ABCDE1234F", "secret-token", "2345 6789 0123", "90000"):
        assert secret not in raw, secret

    assert event["release"] == f"hrms@{APP_VERSION}"
    assert event["tags"]["request_id"] == response.headers["X-Request-ID"]
    assert "ABCDE****F" in event["exception"]["values"][-1]["value"]
    frames = event["exception"]["values"][-1]["stacktrace"]["frames"]
    assert all("vars" not in frame for frame in frames)
    request = event.get("request", {})
    assert "data" not in request and "cookies" not in request

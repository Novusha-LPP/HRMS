"""The published API contract: docs pages, security labels and the error schema."""

import json

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient

from hrms.core.endpoint_docs import ENDPOINT_DOCS
from hrms.core.endpoint_docs.examples import REQUEST_EXAMPLES
from hrms.core.openapi import (
    PLATFORM_SCHEME,
    TAGS_METADATA,
    TENANT_SCHEME,
    build_openapi_schema,
    install_openapi,
)
from hrms.main import app

SCHEMA = build_openapi_schema(app)
OPERATIONS = [
    (method.upper(), path, op)
    for path, item in SCHEMA["paths"].items()
    for method, op in item.items()
]

# Reachable without a token. Adding to this list is a security decision: review it.
PUBLIC = {
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/register-company"),
    ("POST", "/v1/platform/login"),
    ("POST", "/v1/platform/forgot-password"),
    ("POST", "/v1/platform/reset-password"),
    ("GET", "/v1/reports/meta/{module}"),  # static column/filter catalogue, no tenant data
}


def test_every_operation_is_labelled_with_the_token_it_needs():
    public = {(m, p) for m, p, op in OPERATIONS if op["security"] == []}
    assert public == PUBLIC
    for method, path, op in OPERATIONS:
        if (method, path) in PUBLIC:
            continue
        expected = PLATFORM_SCHEME if path.startswith("/v1/platform/") else TENANT_SCHEME
        assert op["security"] == [{expected: []}], (method, path)
        assert {"401", "403"} <= op["responses"].keys(), (method, path)


def test_every_tag_is_documented_and_grouped():
    documented = [t["name"] for t in TAGS_METADATA]
    used = {tag for _, _, op in OPERATIONS for tag in op.get("tags", [])}
    assert used <= set(documented), used - set(documented)
    grouped = [tag for group in SCHEMA["x-tagGroups"] for tag in group["tags"]]
    assert sorted(grouped) == sorted(documented)


def test_operation_ids_are_unique_and_readable():
    ids = [op["operationId"] for _, _, op in OPERATIONS]
    assert len(ids) == len(set(ids))
    assert "login" in ids
    assert not [i for i in ids if "_v1_" in i]


def test_validation_errors_use_the_real_error_envelope():
    text = json.dumps(SCHEMA)
    assert "HTTPValidationError" not in text
    assert "ErrorResponse" in SCHEMA["components"]["schemas"]
    _, _, login = next(o for o in OPERATIONS if o[:2] == ("POST", "/v1/auth/login"))
    assert login["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "429" in login["responses"]


def test_declared_permissions_are_shown():
    _, _, op = next(o for o in OPERATIONS if o[:2] == ("POST", "/v1/users"))
    assert op["description"].startswith("**Requires permission:** `iam.write`")
    _, _, op = next(o for o in OPERATIONS if o[:2] == ("POST", "/v1/leave/types"))
    assert "`leave.write` (all companies)" in op["description"]


def test_every_endpoint_has_reference_text():
    ids = {op["operationId"] for _, _, op in OPERATIONS}
    assert sorted(ids - ENDPOINT_DOCS.keys()) == [], "add these to core/endpoint_docs/"
    assert sorted(ENDPOINT_DOCS.keys() - ids) == [], "these entries match no endpoint"
    for method, path, op in OPERATIONS:
        summary, description = ENDPOINT_DOCS[op["operationId"]]
        assert op["summary"] == summary, (method, path)
        assert description.strip() in op["description"], (method, path)


async def test_docs_pages_are_served_when_enabled():
    docs_app = FastAPI(title="Docs test", docs_url=None, redoc_url=None)
    install_openapi(docs_app, docs_enabled=True)
    async with AsyncClient(transport=ASGITransport(app=docs_app), base_url="http://t") as client:
        swagger = await client.get("/docs")
        redoc = await client.get("/redoc")
    assert swagger.status_code == 200
    assert "authorizeWithPersistOption" in swagger.text
    assert '"persistAuthorization": true' in swagger.text
    assert redoc.status_code == 200


async def test_docs_pages_are_absent_when_disabled():
    docs_app = FastAPI(title="Docs test", openapi_url=None, docs_url=None, redoc_url=None)
    install_openapi(docs_app, docs_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=docs_app), base_url="http://t") as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404


def test_request_examples_match_a_json_body_and_validate():
    by_id = {op["operationId"]: (method, path, op) for method, path, op in OPERATIONS}
    for op_id, example in REQUEST_EXAMPLES.items():
        assert op_id in by_id, f"{op_id} matches no endpoint"
        method, path, op = by_id[op_id]
        assert op["requestBody"]["content"]["application/json"]["example"] == example
    # Each example must pass its route's own request model, or Try it out starts with a 422.
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if isinstance(route, APIRoute) and route.name in REQUEST_EXAMPLES:
            _, errors = ctx.body_field.validate(REQUEST_EXAMPLES[route.name], {}, loc=("body",))
            assert not errors, (route.name, errors)

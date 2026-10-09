# API documentation

The API reference is generated from the backend code, so it always matches the deployed API.
There are three ways to read it:

| URL | What it is | Best for |
|---|---|---|
| `/docs` | Swagger UI. You can call any endpoint from the page. | The frontend team, and trying calls out |
| `/redoc` | ReDoc. A read-only reference on one page, with a grouped sidebar. | Third-party developers reading the API |
| `/openapi.json` | The OpenAPI 3.1 schema | Generating clients, and importing into Postman or Insomnia |

Locally these are at `http://127.0.0.1:8015/docs` (or whichever port the API runs on).

Both pages start with an integration guide. It covers sign-in, tokens, permissions and scope,
IDs, dates, paging, request IDs and the error format. The guide's source is `API_DESCRIPTION`
in [backend/src/hrms/core/openapi.py](../backend/src/hrms/core/openapi.py).

## Using Swagger UI

1. Open `/docs` and expand **Auth → POST /v1/auth/login**.
2. Click **Try it out**, enter `identifier` and `password`, and click **Execute**.
3. Every other request now sends that token, and the padlock icons show as locked. The token
   is kept across page reloads until you click **Authorize → Logout**. When it expires, calls
   return `401`, so sign in again.

For the platform admin endpoints, sign in with **Platform → POST /v1/platform/login** instead.
You can also paste any token into **Authorize** (top right).

Other things the page offers:
- **Filter by tag.** The box at the top filters tags.
- **Deep links.** Each endpoint has its own URL, for example `/docs#/Leave%20Management/create_application`.
- **Requires permission.** This line, where an endpoint declares one, names the permission
  the caller's role needs.

Use a test account, not a real person's login. The testing site holds real employee data.

## Generating a typed client (frontend)

```bash
npx openapi-typescript http://127.0.0.1:8015/openapi.json -o src/api/schema.d.ts
```

The operation IDs are the route function names, for example `create_leave_type` or
`list_balances`. Where two modules use the same function name, the ID gets the tag as a prefix,
for example `leave_management_list_applications` and `recruitment_list_applications`.

## Sharing the API with a third party

On testing and production, `/docs`, `/redoc` and `/openapi.json` return 404, unless
`HRMS_API_DOCS_ENABLED=true` (see [ENVIRONMENTS.md](ENVIRONMENTS.md)). This is intentional,
because the schema is a map of every endpoint. To share the API, either:

- **Send the schema file.** Export it, then share it or host it wherever partners read docs:

  ```bash
  cd backend && uv run python -m hrms.core.openapi openapi.json
  ```

  Any OpenAPI viewer can open it (Swagger Editor, Redocly, Postman, Stoplight).
- **Turn the docs on for an environment.** Set `HRMS_API_DOCS_ENABLED=true` and restart the API.
  Be aware that this makes the endpoint list public on that host.

Each partner should get their own user account, with a role that grants only what they need
(**Users → Create a user account**).

## Keeping the docs accurate

**Endpoint text.** Every endpoint's title and description lives in
[`backend/src/hrms/core/endpoint_docs/`](../backend/src/hrms/core/endpoint_docs/), with one
file per area, keyed by operationId (the route function's name). It is written for someone
outside the team: what the call does, who may call it, the rules that apply, and the errors
specific to it. It replaces the route's own `summary=` and docstring in the published docs,
so router docstrings can stay as notes for maintainers.

When you add or change an endpoint:

- add or update its entry in `endpoint_docs/`. If you rename a route function, rename its key;
- set `response_model=` so the response is shown;
- add `Field(description=..., examples=[...])` to request and response fields that aren't
  obvious.

These are handled for you:

- **Which token an endpoint needs.** This is read from its dependencies (`CurrentUser`,
  `CurrentPlatformAdmin`, or neither).
- **The "Requires permission" line.** This comes from `require_permission(...)` and
  `require_global_permission(...)` (shown as "all companies"). Permission checks made inside
  the function body (`scope.require(...)`) are not detected, so mention those in the
  endpoint's text.
- **The error responses** (401, 403, 422 and 429).

[`tests/test_openapi_docs.py`](../backend/tests/test_openapi_docs.py) fails when:
- an endpoint has no entry in `endpoint_docs/`, or an entry matches no endpoint;
- a tag is missing from `TAGS_METADATA` or `TAG_GROUPS` in `core/openapi.py`;
- an endpoint becomes public (no token) without being added to its `PUBLIC` list. That is
  deliberate: making an endpoint public is a security decision.

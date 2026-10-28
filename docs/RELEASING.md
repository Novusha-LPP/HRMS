# Releasing

One product version covers the API and the web app, because they ship together. The HTTP
API is versioned separately, by its `/v1` path.

## Where the version lives

| File | Role |
|---|---|
| `.release-please-manifest.json` | The released version, as release-please tracks it |
| `backend/pyproject.toml` → `version` | Read at runtime by `hrms/core/version.py`, and reported by `/health` and in logs/error reports |
| `frontend/package.json` → `version` | Injected into the web build (shown under the user menu) |
| `version.txt`, `CHANGELOG.md` | Written by release-please |

Never edit these by hand. release-please bumps all of them in one pull request.

## How a release happens

1. Commit to `main` with [conventional commit](https://www.conventionalcommits.org) messages
   (`feat:`, `fix:`, `perf:`, `refactor:`, `security:` …). The *Commit messages* workflow
   flags any that aren't. A message it can't parse is left out of the release notes.
2. On every push, the *Release* workflow keeps one pull request open, titled
   `chore: release X.Y.Z`. It holds the version bump and the new CHANGELOG entry. A follow-up
   job syncs `backend/uv.lock` and `frontend/package-lock.json` to the new version.
3. When you want to ship, review and merge that pull request. That:
   - tags `vX.Y.Z` and creates the GitHub Release with its notes;
   - builds and pushes the API image `ghcr.io/novusha-lpp/hrms/api:X.Y.Z` (also tagged
     `sha-<commit>`), with the commit and build time baked in;
   - builds and pushes `ghcr.io/novusha-lpp/hrms/web:X.Y.Z` (also tagged `sha-<commit>`),
     with environment settings supplied at container startup;
   - attaches `hrms-frontend-X.Y.Z.tar.gz` to the release for static hosting.
4. A release deploys nothing by itself. Testing runs on EC2 and is deployed from the `testing`
   branch ([Testing CI/CD on EC2](EC2_TESTING_DEPLOYMENT_GUIDE.md)). For other Compose
   deployments, deploy the exact released API and web image versions as described in
   [Environments](ENVIRONMENTS.md). `/health` on the running API reports its
   version and commit, so you can check what is live.

## Which number goes up

We are pre-1.0. Until 1.0:

| Commits since the last release | Bump |
|---|---|
| Any breaking change (`feat!:`, or `BREAKING CHANGE:` in the body) | minor, e.g. 0.3.2 → 0.4.0 |
| `feat:` | patch, e.g. 0.3.2 → 0.3.3 |
| `fix:`, `perf:`, … | patch |

Mark a change as breaking whenever an API client would need to change. For example, when
`GET /v1/leave/applications` started returning pages instead of every row. Release 1.0
with the first paying tenant. From then on, breaking changes bump the major version.

## Database migrations and releases

Deployments run `alembic upgrade head` **before** rolling out the new code, and the old code
keeps serving until the rollout finishes. Every migration must therefore work with the
previous release's code (*expand, then contract*):

- **Expand:** add columns (nullable or with defaults), tables and indexes, and backfill data.
  The old code must keep working.
- **Contract:** drop or rename what the old code used only in a *later* release, once no
  running code reads it.
- Create indexes on large tables `CONCURRENTLY` (see migration 0023).

`/health/ready` reports "migrations pending" (503) when the code expects a newer migration
than the database has. A database *ahead* of the code is normal during a rollout.

## One-time setup

- **Required — pick one:** release-please works by opening a pull request, which GitHub
  forbids to Actions by default ("GitHub Actions is not permitted to create or approve pull
  requests"). Either enable *Settings → Actions → General → Workflow permissions → Allow
  GitHub Actions to create and approve pull requests*, or add the token below.
- **Recommended:** add a repository secret `RELEASE_PLEASE_TOKEN` holding a fine-grained PAT
  or GitHub App token with *contents* and *pull requests* write access. Pull requests opened
  with the default `GITHUB_TOKEN` don't trigger other workflows, so without it the release
  PR gets no CI run.
- The history before this process starts at commit `da08bb8` (`bootstrap-sha` in
  `release-please-config.json`). `CHANGELOG.md` records that state as 0.1.0. Tag it once
  with `git tag v0.1.0 da08bb8 && git push origin v0.1.0` so the first GitHub Release has
  something to compare against.

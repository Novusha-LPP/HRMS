"""Validate deployment inputs without printing credentials or evaluating env files."""

import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ValueError(f"Invalid or duplicate setting in {path.name}")
        if value.startswith(("'", '"')) or "\x00" in value:
            raise ValueError(f"Use literal, unquoted values for {key}")
        values[key] = value
    return values


def validate_images(data: dict) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("commit", "")):
        raise ValueError("Deployment commit must be a full Git SHA")
    pattern = r"\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[0-9a-f]{64}"
    for key in ("api", "web"):
        if not re.fullmatch(pattern, data.get(key, "")):
            raise ValueError(f"The {key} image must be an ECR image pinned by digest")
    if data["api"].split("/")[0] != data["web"].split("/")[0]:
        raise ValueError("Both images must use the same ECR registry")
    return f"HRMS_API_IMAGE={data['api']}\nHRMS_WEB_IMAGE={data['web']}\n"


def database_url(value: str, username: str):
    url = urlsplit(value)
    if (
        url.scheme != "postgresql+asyncpg"
        or unquote(url.username or "") != username
        or not url.password
        or not (url.hostname or "").endswith(".rds.amazonaws.com")
        or url.port != 5432
        or url.path in ("", "/", "/postgres", "/template0", "/template1")
        or parse_qs(url.query) != {"ssl": ["verify-full"]}
    ):
        raise ValueError(f"Invalid verified RDS connection for {username}")
    return url


def validate_settings(runtime: dict, migrate: dict, deploy: dict) -> None:
    allowed_migrate = {"HRMS_DATABASE_URL", "HRMS_APP_ROLE_PASSWORD", "HRMS_PLATFORM_ROLE_PASSWORD"}
    if set(migrate) != allowed_migrate:
        raise ValueError("Migration env must contain only the owner URL and the two role passwords")
    forbidden = allowed_migrate - {"HRMS_DATABASE_URL"}
    forbidden |= {"HRMS_DB_OWNER_PASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    if forbidden & runtime.keys():
        raise ValueError(
            "Runtime env must not contain owner/role passwords or static AWS credentials"
        )
    if runtime.get("HRMS_DATABASE_URL") != runtime.get("HRMS_APP_DATABASE_URL"):
        raise ValueError("Runtime HRMS_DATABASE_URL must equal the restricted app connection")
    urls = [
        database_url(runtime.get("HRMS_APP_DATABASE_URL", ""), "hrms_app"),
        database_url(runtime.get("HRMS_PLATFORM_DATABASE_URL", ""), "hrms_platform"),
    ]
    owner_name = unquote(urlsplit(migrate["HRMS_DATABASE_URL"]).username or "")
    if owner_name in ("", "hrms_app", "hrms_platform"):
        raise ValueError("Migration connection needs a separate database owner")
    urls.append(database_url(migrate["HRMS_DATABASE_URL"], owner_name))
    if len({(u.hostname, u.port, u.path) for u in urls}) != 1:
        raise ValueError("All database roles must connect to the same RDS database")
    passwords = [unquote(u.password or "") for u in urls]
    if len(set(passwords)) != 3:
        raise ValueError("Database credentials must be different for all three roles")
    for index, key in enumerate(("HRMS_APP_ROLE_PASSWORD", "HRMS_PLATFORM_ROLE_PASSWORD")):
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{24,}", migrate[key])
            or migrate[key] != passwords[index]
        ):
            raise ValueError(f"{key} must be a long URL-safe secret matching the runtime URL")
    for key in ("HRMS_SECRET_KEY", "HRMS_METRICS_TOKEN"):
        value = runtime.get(key, "")
        if len(value) < 32 or "REPLACE" in value or "change-me" in value:
            raise ValueError(f"Set a random {key} of at least 32 characters")
    try:
        keys = runtime["HRMS_FIELD_ENCRYPTION_KEYS"].split(",")
        ids = set()
        for item in keys:
            key_id, material = item.split(":", 1)
            if not key_id or key_id == "dev" or key_id in ids:
                raise ValueError()
            ids.add(key_id)
            if len(base64.b64decode(material, altchars=b"-_", validate=True)) != 32:
                raise ValueError()
    except (KeyError, ValueError):
        raise ValueError("Set valid, unique HRMS_FIELD_ENCRYPTION_KEYS with 32-byte keys") from None
    try:
        pay_keys = runtime["HRMS_PAYROLL_ENCRYPTION_KEYS"].split(",")
        pay_ids = set()
        for item in pay_keys:
            key_id, material = item.split(":", 1)
            if not key_id or key_id == "dev" or key_id in pay_ids or item in keys:
                raise ValueError()
            pay_ids.add(key_id)
            if len(base64.b64decode(material, altchars=b"-_", validate=True)) != 32:
                raise ValueError()
    except (KeyError, ValueError):
        raise ValueError(
            "Set valid, unique HRMS_PAYROLL_ENCRYPTION_KEYS (32-byte keys, not the PII keys)"
        ) from None
    pepper = runtime.get("HRMS_PAYROLL_PEPPER", "")
    if len(pepper) < 32 or "REPLACE" in pepper:
        raise ValueError("Set a random HRMS_PAYROLL_PEPPER of at least 32 characters")
    origins = runtime.get("HRMS_CORS_ORIGINS", "").split(",")
    for value in origins + [deploy.get("HRMS_WEB_API_URL", "")]:
        url = urlsplit(value.strip())
        if (
            url.scheme != "https"
            or not url.netloc
            or url.path
            or url.query
            or url.fragment
            or url.username
        ):
            raise ValueError(
                "CORS origins and HRMS_WEB_API_URL must be HTTPS origins without a trailing slash"
            )
    if "*" in deploy.get("HRMS_FORWARDED_ALLOW_IPS", ""):
        raise ValueError("Forwarded proxy trust must be restricted")
    if runtime.get("HRMS_DOCUMENT_STORAGE", "local") == "s3" and not runtime.get(
        "HRMS_DOCUMENT_S3_BUCKET"
    ):
        raise ValueError("S3 document storage needs HRMS_DOCUMENT_S3_BUCKET")


def main() -> None:
    release = Path(sys.argv[1]).resolve()
    config = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/etc/hrms")
    data = json.loads((release / "images.json").read_text())
    image_env = validate_images(data)
    validate_settings(
        load_env(config / "testing.runtime.env"),
        load_env(config / "testing.migrate.env"),
        load_env(config / "testing.deploy.env"),
    )
    path = release / "images.env"
    path.write_text(image_env)
    os.chmod(path, 0o600)
    print("Deployment settings validated")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        # Never format input values or connection URLs into these messages.
        print(
            f"Deployment configuration failed: {type(exc).__name__}. Check the env templates.",
            file=sys.stderr,
        )
        sys.exit(1)

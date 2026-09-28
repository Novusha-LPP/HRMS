from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HRMS_", extra="ignore")

    # Database
    # Used by Alembic and as the app's fallback connection — normally the
    # Postgres superuser, since migrations need DDL rights.
    database_url: str = "postgresql+asyncpg://hrms:hrms@localhost:5432/hrms"
    # The RUNNING APP should instead connect as a role with NOSUPERUSER and
    # NOBYPASSRLS (see migration 0005) so PostgreSQL's row-level security
    # policies are an active second layer of tenant isolation, not just the
    # application's own WHERE tenant_id = ... filters. Falls back to
    # database_url when unset so a fresh checkout still runs.
    app_database_url: str | None = None
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Security
    secret_key: str = "change-me-before-production"
    algorithm: str = "HS256"
    # No refresh-token flow yet, so this is a full work session, not a typical
    # short-lived access token. Re-authenticate after expiry.
    access_token_expire_minutes: int = 480

    # Application
    app_name: str = "HRMS Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"

    # CORS — comma-separated origins
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Storage
    storage_dir: str = "storage"
    max_upload_bytes: int = 10 * 1024 * 1024

    @model_validator(mode="after")
    def production_configuration(self):
        if self.environment == "production":
            if self.secret_key == "change-me-before-production" or len(self.secret_key) < 32:
                raise ValueError(
                    "Production requires a random signing secret of at least 32 characters"
                )
            if not self.app_database_url:
                raise ValueError("Production requires HRMS_APP_DATABASE_URL")
            if self.debug:
                raise ValueError("Debug mode must be disabled in production")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()

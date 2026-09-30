from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# The hrms_app role is created by migration 0005 with this password, which is
# public (it's in the repository). Fine on a laptop, never in production.
KNOWN_DEV_APP_ROLE_PASSWORD = "hrms_app_dev_password"


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
    # (The version is not a setting: see core/version.py.)
    debug: bool = False
    environment: str = "development"
    # Adds Server-Timing / X-DB-Queries headers with each request's statement count and DB time
    # (core/perf.py). For development, staging and benchmarks; leave off in production.
    query_metrics: bool = False

    # Enterprise Logging
    log_level: str = "INFO"
    log_format: str = "console"  # "console" | "json"
    log_slow_request_threshold_ms: float = 1000.0
    log_exclude_paths: str = "/health"

    # Error tracking (core/error_tracking.py). Off unless a DSN is set.
    sentry_dsn: str | None = None
    # Defaults to `environment`; set to tell apart e.g. staging and production.
    sentry_environment: str | None = None
    # Share of requests traced for performance (0 = errors only).
    sentry_traces_sample_rate: float = 0.0

    # Prometheus metrics at GET /metrics (core/metrics.py).
    metrics_enabled: bool = True
    # Bearer token the scraper must send. Required in production while metrics are enabled.
    metrics_token: str | None = None

    # CORS — comma-separated origins
    cors_origins: str = "http://localhost:3000,http://localhost:5173,https://testinghrms.alvision.in,http://testinghrms.alvision.in"

    # Storage
    storage_dir: str = "storage"
    max_upload_bytes: int = 10 * 1024 * 1024

    # Brute-force protection for the unauthenticated endpoints (see core/throttle.py).
    # Counters live in the database, so they hold across API workers and restarts.
    throttle_enabled: bool = True
    # Wrong passwords per identifier + client IP before that pair is locked out …
    login_max_failures: int = 5
    # … per identifier from any source (higher, so one attacker can't lock a
    # victim out too easily, but a distributed guesser still gets stopped) …
    login_identifier_max_failures: int = 25
    # … and per client IP (generous: a whole factory floor can share one NAT address).
    login_ip_max_failures: int = 100
    login_lockout_minutes: int = 15
    # Anonymous POST /v1/auth/register-company attempts per client IP per hour.
    register_max_per_hour: int = 5
    # Set false once every tenant is created from the platform console.
    allow_public_registration: bool = True

    # Last-resort attendance policy, used only when no template is assigned to
    # an employee, their department, their company or their tenant. Tenants
    # should define their own default template; these are just the deployment's
    # fallback and can be changed without touching code.
    default_timezone: str = "Asia/Kolkata"
    default_work_start: str = "09:30"
    default_work_end: str = "18:30"
    default_grace_late_minutes: int = 15
    default_grace_early_minutes: int = 15
    default_financial_year_start_month: int = 4

    @model_validator(mode="after")
    def production_configuration(self):
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got '{self.log_level}'")
        self.log_level = self.log_level.upper()

        if self.environment == "production":
            if self.secret_key == "change-me-before-production" or len(self.secret_key) < 32:
                raise ValueError(
                    "Production requires a random signing secret of at least 32 characters"
                )
            if not self.app_database_url:
                raise ValueError("Production requires HRMS_APP_DATABASE_URL")
            if make_url(self.app_database_url).password == KNOWN_DEV_APP_ROLE_PASSWORD:
                raise ValueError(
                    "HRMS_APP_DATABASE_URL still uses the published development password for "
                    "the hrms_app role — run ALTER ROLE hrms_app PASSWORD '<random>' and update it"
                )
            if self.database_url and make_url(self.database_url).password == "hrms":
                raise ValueError(
                    "HRMS_DATABASE_URL still uses the published development password — "
                    "set a production HRMS_DATABASE_URL with a secure password"
                )
            if self.debug:
                raise ValueError("Debug mode must be disabled in production")
            if self.metrics_enabled and not self.metrics_token:
                raise ValueError(
                    "Production serves /metrics only behind a scrape token: set "
                    "HRMS_METRICS_TOKEN (or HRMS_METRICS_ENABLED=false)"
                )
            # Default to JSON format in production unless explicitly specified otherwise
            if self.log_format == "console":
                self.log_format = "json"
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def log_exclude_paths_list(self) -> list[str]:
        return [p.strip() for p in self.log_exclude_paths.split(",") if p.strip()]


settings = Settings()

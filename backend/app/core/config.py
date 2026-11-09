"""Environment-based configuration. All secrets come from the environment, never from code."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=None, extra="ignore")

    app_env: str = Field(default="production", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database_url: str = Field(alias="DATABASE_URL")

    # Master key used to derive the Fernet key that encrypts provider credentials at rest.
    app_secret_key: str = Field(alias="APP_SECRET_KEY")
    # Optional shared access token for the API/UI. Strongly recommended when exposed through a tunnel.
    app_auth_token: str = Field(default="", alias="APP_AUTH_TOKEN")
    # Public base URL (used for OAuth redirect URIs, e.g. https://growos.example.com).
    public_base_url: str = Field(default="http://localhost:8888", alias="PUBLIC_BASE_URL")

    artifacts_dir: str = Field(default="/data/artifacts", alias="ARTIFACTS_DIR")

    worker_concurrency: int = Field(default=2, alias="WORKER_CONCURRENCY")
    # Which queue this worker serves: "default", "crawler", or blank to take every task (single-worker setups and
    # local development). See app.tasks.registry.TASK_QUEUES.
    worker_queue: str = Field(default="", alias="WORKER_QUEUE")
    worker_poll_interval_seconds: float = Field(default=2.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    job_heartbeat_timeout_seconds: int = Field(default=900, alias="JOB_HEARTBEAT_TIMEOUT_SECONDS")

    siteone_bin: str = Field(default="/opt/siteone-crawler/siteone-crawler", alias="SITEONE_BIN")
    crawl_max_urls_default: int = Field(default=500, alias="CRAWL_MAX_URLS_DEFAULT")
    crawl_max_reqs_per_sec: int = Field(default=5, alias="CRAWL_MAX_REQS_PER_SEC")
    crawl_user_agent: str = Field(default="GrowOS-Crawler/0.1 (+https://github.com/growos)", alias="CRAWL_USER_AGENT")

    # Outbound HTTP safety
    outbound_timeout_seconds: float = Field(default=20.0, alias="OUTBOUND_TIMEOUT_SECONDS")
    outbound_max_bytes: int = Field(default=5_000_000, alias="OUTBOUND_MAX_BYTES")
    # Hosts the SSRF guard may reach even though they resolve to a private address — for services you run
    # alongside GrowOS, e.g. an internal aggregator a custom adapter fetches from. Operator-controlled,
    # never settable from the UI.
    outbound_allow_hosts: str = Field(default="", alias="OUTBOUND_ALLOW_HOSTS")

    # Simple in-memory rate limit for mutating API calls (requests per minute per client IP).
    api_rate_limit_per_minute: int = Field(default=240, alias="API_RATE_LIMIT_PER_MINUTE")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    # App-level Google OAuth client (one-time setup in Google Cloud Console). Enables one-click "Connect with Google"
    # for Search Console and Analytics. Per-connection client credentials, if entered, take precedence.
    google_oauth_client_id: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", alias="GOOGLE_OAUTH_CLIENT_SECRET")
    # App-level Google API key for PageSpeed Insights / Chrome UX Report (raises the keyless quota). Optional.
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    # Google AI Studio key for Gemini. Separate from GOOGLE_API_KEY on purpose: that one is a Cloud console key
    # for PageSpeed/CrUX and is normally restricted to those APIs, so it cannot answer for the Generative
    # Language API. Optional; a key entered on the connection overrides it.
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")  # local | openai | gemini
    # App-level SerpApi key, shared by the three SerpApi providers (live SERP, AI surfaces, Extract). Optional:
    # a key entered on a connection overrides it. See ENV_CREDENTIALS in app.services.providers.
    serpapi_api_key: str = Field(default="", alias="SERPAPI_API_KEY")
    # Optional deployment-wide token for Apify-backed integrations.
    apify_api_token: str = Field(default="", alias="APIFY_API_TOKEN")
    # Bing Webmaster Tools API key. Account-wide, so one key covers every verified site. Optional: a key entered
    # on the connection overrides it. See ENV_CREDENTIALS in app.services.providers.
    bing_api_key: str = Field(default="", alias="BING_API_KEY")

    # First admin account, created on startup when no users exist yet.
    admin_email: str = Field(default="", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    session_days: int = Field(default=30, alias="SESSION_DAYS")

    # Outbound email (notifications & weekly digest). If unset, notifications are still recorded in-app and logged.
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")

    # Cost guardrail: default monthly AI token budget per project (0 = unlimited). Overridable per project.
    default_monthly_token_budget: int = Field(default=0, alias="DEFAULT_MONTHLY_TOKEN_BUDGET")

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @field_validator("app_secret_key")
    @classmethod
    def _secret_strength(cls, v: str) -> str:
        if len(v) < 32 or v.startswith("change-me"):
            raise ValueError("APP_SECRET_KEY must be at least 32 random characters (see .env.example)")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

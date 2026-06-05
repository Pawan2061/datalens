from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    app_name: str = "DataLens Analytics"
    cors_origins: list[str] = ["*"]
    llm_provider: str = "openai"  # "mock", "openai", "azure", or "anthropic"
    mock_llm_delay_ms: int = 500
    max_query_timeout_seconds: int = 30
    max_query_rows: int = 10000

    # OpenAI (direct)
    openai_api_key: str = ""
    openai_planner_model: str = "gpt-4o"
    openai_worker_model: str = "gpt-4.1-mini"

    # Azure OpenAI
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_planner_deployment: str = "gpt-4o"
    azure_worker_deployment: str = "gpt-4.1-mini"
    azure_api_version: str = "2025-01-01-preview"

    # Anthropic (direct API or via Azure AI Foundry)
    anthropic_api_key: str = ""          # standard key from console.anthropic.com
    anthropic_foundry_key: str = ""      # Azure AI Foundry key (takes precedence if set)
    anthropic_foundry_url: str = ""      # Azure AI Foundry endpoint (leave blank for direct API)
    anthropic_planner_model: str = "claude-sonnet-4-5"
    anthropic_worker_model: str = "claude-haiku-4-5"
    # Prompt caching: cache the static prefix (rules + workspace profile + API
    # tool descriptions) so subsequent turns in a session pay only 0.1x for
    # those tokens. Only active when llm_provider == "anthropic".
    anthropic_prompt_caching: bool = True
    # Skip caching when the cacheable prefix is below this token count — the
    # 1.25x write surcharge is not worth it for small prefixes. Anthropic's
    # own minimum is 1024 (Sonnet) / 2048 (Haiku); we pick the safer upper
    # bound so the flag is a no-op on tiny prompts.
    anthropic_prompt_cache_min_tokens: int = 2048

    # Cache warming: Anthropic's ephemeral prompt cache has a 5-min TTL. For
    # workspaces with bursty traffic, gaps >5 min force the next request to
    # repay cache_creation (1.25x input) instead of cache_read (0.1x). A
    # background loop re-pings the cached prefix with max_tokens=1 on an
    # interval shorter than the TTL, keeping it hot for real traffic.
    # Disabled by default — enable per deployment after verifying traffic
    # patterns make warming cheaper than the avoided cold starts.
    anthropic_cache_warming_enabled: bool = False
    anthropic_cache_warming_interval_seconds: int = 240        # < 300s TTL
    anthropic_cache_warming_active_window_seconds: int = 900   # only warm workspaces active in last 15m
    anthropic_cache_warming_max_concurrent: int = 2            # bound parallel pings

    # Google Gemini (FREE tier for quick mode)
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Schema cache TTL in seconds
    schema_cache_ttl: int = 3600  # 1 hour (was 10 min — schemas rarely change)

    # Auth / Admin
    jwt_secret: str = "CHANGE-ME-in-production"  # override via JWT_SECRET env var
    admin_email: str = ""  # first registered user gets admin; override via ADMIN_EMAIL
    google_client_id: str = ""  # Google OAuth Client ID; override via GOOGLE_CLIENT_ID
    github_client_id: str = ""  # for GitHub SSO
    github_client_secret: str = ""
    recaptcha_secret_key: str = ""        # legacy v2 secret (unused when Enterprise is configured)
    recaptcha_project_id: str = ""        # GCP project ID for Enterprise verification
    recaptcha_gcp_api_key: str = ""       # GCP API key with reCAPTCHA Enterprise API enabled
    recaptcha_enterprise_site_key: str = ""  # Enterprise site key (for token binding check)

    # DataLens persistence (PostgreSQL — Neon or any Postgres URL)
    database_url: str = ""  # e.g. postgresql+psycopg://user:pass@host/db

    # Azure Cosmos DB — only needed if users connect a Cosmos DB as a data source
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "DataLensDB"

    # Email / SMTP
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_pass: str = ""
    email_smtp_from: str = ""

    # Rate limiting — per-user burst protection on the chat endpoint.
    # In-memory sliding window (no Redis in the stack). Admins bypass.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 15
    rate_limit_per_hour: int = 150

    # Cost alerts — email the team when a user's spend in the current day
    # (today_cost_usd, resets at UTC midnight) first crosses the threshold for
    # their role. Fires at most once per user per day. Alert-only; users are
    # not blocked. No-op unless SMTP is configured and recipients are set.
    cost_alert_threshold_usd: float = 2.0  # regular users
    cost_alert_threshold_usd_admin: float = 10.0  # admins

    # Daily hard block — a regular customer whose same-day spend (today_cost_usd,
    # resets at UTC midnight) reaches this is blocked from chatting until an admin
    # re-approves them. Privileged roles (admin/manager/moderator) are never
    # blocked. 0 disables the block.
    cost_block_threshold_usd_per_day: float = 4.0
    cost_alert_recipients: list[str] = [
        "vaibhav@ainocular.com",
        "bhairav@ainocular.com",
        "pawan@ainocular.com",
    ]

    class Config:
        env_file = str(_ENV_FILE)


settings = Settings()

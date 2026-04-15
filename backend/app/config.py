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

    # Google Gemini (FREE tier for quick mode)
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Schema cache TTL in seconds
    schema_cache_ttl: int = 600  # 10 minutes

    # Auth / Admin
    jwt_secret: str = "CHANGE-ME-in-production"  # override via JWT_SECRET env var
    admin_email: str = ""  # first registered user gets admin; override via ADMIN_EMAIL
    google_client_id: str = ""  # Google OAuth Client ID; override via GOOGLE_CLIENT_ID
    github_client_id: str = ""  # for GitHub SSO
    github_client_secret: str = ""

    # DataLens persistence (PostgreSQL — Neon or any Postgres URL)
    database_url: str = ""  # e.g. postgresql+psycopg://user:pass@host/db

    # Azure Cosmos DB — only needed if users connect a Cosmos DB as a data source
    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "DataLensDB"

    class Config:
        env_file = str(_ENV_FILE)


settings = Settings()

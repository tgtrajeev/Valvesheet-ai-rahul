"""Application configuration loaded from environment variables."""

import os
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    anthropic_api_key: str = ""

    # Database — Render provides DATABASE_URL as postgres://, asyncpg needs postgresql+asyncpg://
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/valve_agent"

    # Existing services (called via HTTP)
    ml_api_base_url: str = "http://localhost:8080/api"
    backend_api_base_url: str = "http://localhost:8000/api"

    # Server
    port: int = 8001

    # Agent
    agent_model: str = "claude-sonnet-4-20250514"
    agent_temperature: float = 0.1
    agent_max_tokens: int = 4096
    agent_max_tool_calls: int = 50

    # PMS external API (for syncing PMS from project systems)
    pms_api_base_url: str = ""          # empty = disabled; set when API is ready
    pms_api_key: str = ""
    pms_sync_enabled: bool = False      # flip to True once API is live

    # CORS — comma-separated origins for production
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = ""

    # Paths
    data_dir: Path = Path(__file__).parent / "data"

    @property
    def allowed_origins(self) -> list[str]:
        """Build CORS origins list from config."""
        origins = set()
        if self.frontend_url:
            origins.add(self.frontend_url.rstrip("/"))
        if self.cors_origins:
            for o in self.cors_origins.split(","):
                o = o.strip().rstrip("/")
                if o:
                    origins.add(o)
        return list(origins) or ["*"]

    @property
    def async_database_url(self) -> str:
        """Normalize DATABASE_URL for asyncpg."""
        url = self.database_url
        # Render provides postgres://, SQLAlchemy needs postgresql+asyncpg://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# Also check PORT env var (Render sets this)
if os.environ.get("PORT"):
    settings.port = int(os.environ["PORT"])

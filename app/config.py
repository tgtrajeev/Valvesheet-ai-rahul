"""Application configuration loaded from environment variables."""

import os
from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    anthropic_api_key: str = ""

    # LLM provider: anthropic | gemini | openai | qwen | deepseek | glm
    llm_provider: str = "anthropic"

    # ── Gemini (Google AI Studio, OpenAI-compatible endpoint) ──
    # Recommended Claude replacement. Flash = best value; Pro = near-Claude quality.
    gemini_api_key: str = ""
    gemini_api_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-2.5-flash"   # or "gemini-2.5-pro" for higher quality

    # ── OpenAI (native) ──
    openai_api_key: str = ""
    openai_api_base_url: str = ""             # empty = OpenAI default endpoint
    openai_model: str = "gpt-4.1-mini"

    # ── Qwen (Alibaba DashScope, OpenAI-compatible) ──
    qwen_api_key: str = ""
    qwen_api_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen3-max"

    # ── DeepSeek (OpenAI-compatible) ──
    deepseek_api_key: str = ""
    deepseek_api_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # ── GLM (Zhipu AI / Cerebras, OpenAI-compatible) ──
    glm_api_key: str = ""
    glm_api_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4-plus"

    # ── OpenRouter (gateway to many models, OpenAI-compatible) ──
    openrouter_api_key: str = ""
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"   # set any OpenRouter model slug

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

    # Render-deployed PMS sources (consumed by scripts/sync_from_render.py).
    # Empty by default — only set in .env when syncing from Render.
    pms_generator_database_url: str = ""
    valve_agent_database_url: str = ""

    # CORS — comma-separated origins for production
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = ""

    # Paths
    data_dir: Path = Path(__file__).parent / "data"

    def active_llm_config(self) -> dict:
        """Resolve (provider, api_key, base_url, model) for the active LLM_PROVIDER.

        Every non-Anthropic provider is OpenAI-compatible and routed through the
        same provider class — only the base_url / key / model differ.
        """
        p = self.llm_provider.strip().lower()
        # provider -> (api_key, base_url, model)
        table = {
            "anthropic": (self.anthropic_api_key, "", self.agent_model),
            "gemini":    (self.gemini_api_key, self.gemini_api_base_url, self.gemini_model),
            "google":    (self.gemini_api_key, self.gemini_api_base_url, self.gemini_model),
            "openai":    (self.openai_api_key, self.openai_api_base_url, self.openai_model),
            "qwen":      (self.qwen_api_key, self.qwen_api_base_url, self.qwen_model),
            "dashscope": (self.qwen_api_key, self.qwen_api_base_url, self.qwen_model),
            "deepseek":  (self.deepseek_api_key, self.deepseek_api_base_url, self.deepseek_model),
            "glm":       (self.glm_api_key, self.glm_api_base_url, self.glm_model),
            "zhipu":     (self.glm_api_key, self.glm_api_base_url, self.glm_model),
            "openrouter":(self.openrouter_api_key, self.openrouter_api_base_url, self.openrouter_model),
        }
        api_key, base_url, model = table.get(p, table["anthropic"])
        return {"provider": p, "api_key": api_key, "base_url": base_url, "model": model}

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

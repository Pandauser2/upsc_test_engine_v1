"""
Application configuration from environment variables.
Loads .env from the backend directory so API keys are found regardless of cwd.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env next to backend/ (parent of app/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Load and validate config from env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
    )

    # Database: sqlite for testing without Docker, postgresql for production
    database_url: str = "sqlite:///./upsc_dev.db"

    # JWT (used from Step 3)
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # LLM: default provider is Claude (Anthropic). Set LLM_PROVIDER=openai to use OpenAI.
    llm_provider: str = "claude"
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""

    prompt_version: str = "mcq_v1"
    max_generation_time_seconds: int = 300
    min_extraction_words: int = 500

    # File uploads (MVP: max 100 pages per PDF; reject larger at upload)
    upload_dir: Path = Path("./uploads")
    max_pdf_pages: int = 100

    # Chunking: semantic (spaCy) or fixed
    chunk_mode: str = "semantic"
    chunk_size: int = 1500
    chunk_overlap_fraction: float = 0.2

    # RAG (MCQ generation)
    rag_top_k: int = 5
    rag_embedding_model: str = "all-MiniLM-L6-v2"

    # Celery (optional; use when concurrency or long jobs need a queue)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # CORS: comma-separated origins
    cors_origins: str = "http://localhost:3000"

    debug: bool = False

    @property
    def active_llm_model(self) -> str:
        """Model name for the currently configured LLM provider (for display/storage)."""
        p = (self.llm_provider or "claude").strip().lower()
        if p == "openai":
            return self.openai_model
        return self.claude_model


settings = Settings()

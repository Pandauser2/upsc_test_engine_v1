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
    claude_timeout_seconds: float = 120.0  # HTTP timeout so requests don't hang
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""

    prompt_version: str = "mcq_v1"
    max_generation_time_seconds: int = 300
    # Base stale timeout (seconds). Dynamic timeout = this + (num_chunks // 10 * 60). Used so long runs (e.g. 100-page PDF) aren't marked failed_timeout.
    max_stale_generation_seconds: int = 1200
    min_extraction_words: int = 500

    # File uploads (MVP: max 100 pages per PDF; reject larger at upload)
    upload_dir: Path = Path("./uploads")
    max_pdf_pages: int = 100
    # On-demand extraction (GET /documents/{id}/extract when text empty): max wait in seconds; avoids hanging.
    extract_on_demand_timeout_seconds: int = 600

    # Chunking: semantic (spaCy) or fixed
    chunk_mode: str = "semantic"
    chunk_size: int = 1500
    chunk_overlap_fraction: float = 0.2

    # RAG (MCQ generation). Set true to allow global RAG when doc has enough chunks (> rag_min_chunks_for_global).
    use_global_rag: bool = True
    # Enable global outline + RAG only when chunk count > this (default 20 → 21+ chunks). Env: RAG_MIN_CHUNKS_FOR_GLOBAL.
    rag_min_chunks_for_global: int = 20
    rag_top_k: int = 5
    rag_embedding_model: str = "all-MiniLM-L6-v2"
    # Optional: filter retrieved chunks by L2 distance (keep if distance <= this). ~0.9 ≈ cosine > 0.6.
    rag_relevance_max_l2: float | None = None
    # Max chunks to summarize for global outline (caps outline latency).
    rag_outline_max_chunks: int = 10
    # Candidates to generate before validation filter; cap at 20 (MVP)
    mcq_candidate_count: int = 4

    # Celery (optional; use when concurrency or long jobs need a queue)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # CORS: comma-separated origins
    cors_origins: str = "http://localhost:3000"

    # Quality baseline: export_result=true + ENABLE_EXPORT=true → save MCQs to exports/{test_id}.json; extra logging
    enable_export: bool = False
    exports_dir: Path = Path("./exports")

    debug: bool = False

    @property
    def active_llm_model(self) -> str:
        """Model name for the currently configured LLM provider (for display/storage)."""
        p = (self.llm_provider or "claude").strip().lower()
        if p == "openai":
            return self.openai_model
        return self.claude_model


settings = Settings()

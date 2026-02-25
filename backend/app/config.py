"""
Application configuration from environment variables.
Loads .env from the backend directory so API keys are found regardless of cwd.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env next to backend/ (parent of app/) — load explicitly so key is set even when run from repo root
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"

if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE, override=False)  # load backend/.env into os.environ so Settings sees GEMINI_API_KEY
else:
    # Fallback: try backend/.env relative to cwd (e.g. when running from repo root)
    import os
    _cwd_env = Path(os.getcwd()) / "backend" / ".env"
    if _cwd_env.exists():
        from dotenv import load_dotenv
        load_dotenv(_cwd_env, override=False)


class Settings(BaseSettings):
    """Load and validate config from env."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",  # ignore legacy CLAUDE_API_KEY, OPENAI_API_KEY, etc.
    )

    # Database: sqlite for testing without Docker, postgresql for production
    database_url: str = "sqlite:///./upsc_dev.db"

    # Environment: set ENV=production in production; used to enforce SECRET_KEY.
    env: str = ""

    # JWT (used from Step 3). In production (ENV=production), SECRET_KEY must be set.
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # LLM: Gemini only. Set GEN_MODEL_NAME and GEMINI_API_KEY.
    gen_model_name: str = "gemini-1.5-flash-002"
    gemini_api_key: str = ""

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
    # OCR trigger: only run OCR when native text per page < this (env OCR_THRESHOLD). Tighten to 50 for text-heavy NCERT PDFs.
    ocr_threshold: int = 50

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
        """Model name for display/storage."""
        return (getattr(self, "gen_model_name", None) or "gemini-1.5-flash-002").strip()


settings = Settings()

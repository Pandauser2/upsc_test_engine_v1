"""
Application configuration from environment variables.
Loads .env from the backend directory so API keys are found regardless of cwd.
"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default model for generateContent (v1beta). gemini-2.0-flash is no longer available to new users.
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Models that return 404 or are unsupported. Normalized at config load to _DEFAULT_GEMINI_MODEL.
_UNSUPPORTED_GEMINI_MODELS = frozenset({
    "gemini-1.5-flash-002", "gemini-1.5-flash-001", "gemini-1.5-flash",
    "gemini-1.5-pro", "gemini-1.5-pro-001", "gemini-1.5-pro-002",
    "gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-2.0-flash-lite", "gemini-2.0-flash-lite-001",
})


def _normalize_gen_model(v: str) -> str:
    """Ensure gen_model_name is supported by generateContent (avoids 404 from old .env)."""
    s = (v or _DEFAULT_GEMINI_MODEL).strip()
    if not s:
        return _DEFAULT_GEMINI_MODEL
    if s in _UNSUPPORTED_GEMINI_MODELS or s.startswith("gemini-1.5-flash-") or s.startswith("gemini-1.5-pro") or s.startswith("gemini-2.0-flash"):
        return _DEFAULT_GEMINI_MODEL
    return s

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

    # LLM: Gemini only. Set GEN_MODEL_NAME and GEMINI_API_KEY. Use a model supported by generateContent (e.g. gemini-2.5-flash).
    # Unsupported/deprecated models are normalized to gemini-2.5-flash to avoid 404.
    gen_model_name: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    # If True and Gemini returns 0 MCQs (e.g. invalid JSON), retry once with Claude (requires ANTHROPIC_API_KEY).
    claude_fallback: bool = False
    # Gemini MCQ generation: max output tokens (env GEMINI_MAX_OUTPUT_TOKENS). Default 4000 for fast path.
    gemini_max_output_tokens: int = 4000

    @field_validator("gen_model_name", mode="before")
    @classmethod
    def _resolve_gen_model(cls, v: str) -> str:
        return _normalize_gen_model(v) if isinstance(v, str) else _DEFAULT_GEMINI_MODEL

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
    # Fast path: when extracted text length < this, skip chunking/RAG/parallel/validation and send full doc in one Gemini call. Env: MAX_SINGLE_CALL_CHARS.
    max_single_call_chars: int = 600000

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
        return (getattr(self, "gen_model_name", None) or _DEFAULT_GEMINI_MODEL).strip()


settings = Settings()

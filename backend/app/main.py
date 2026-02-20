"""
FastAPI application entrypoint.
APIs: auth, topics, tests. Run with: uvicorn app.main:app --reload --port 8000
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.topics import router as topics_router
from app.api.tests import router as tests_router

app = FastAPI(
    title="UPSC Test Engine API",
    description="Faculty-facing API: documents → MCQs with answer, explanation, difficulty.",
    version="0.1.0",
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(topics_router)
app.include_router(tests_router)


@app.on_event("startup")
def startup():
    """Init SQLite DB and log LLM key status."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _log = logging.getLogger("app.main")
    provider = (settings.llm_provider or "claude").strip().lower()
    if provider == "claude":
        key = (settings.claude_api_key or "").strip()
        if key:
            _log.info("Claude: API key loaded (len=%s). Real API will be used for MCQ generation.", len(key))
        else:
            _log.warning("Claude: No API key. Set CLAUDE_API_KEY in backend/.env for real generation (using mock).")
    else:
        key = (settings.openai_api_key or "").strip()
        if key:
            _log.info("OpenAI: API key loaded. Real API will be used.")
        else:
            _log.warning("OpenAI: No API key. Set OPENAI_API_KEY in backend/.env (using mock).")
    from app.database import init_sqlite_db
    init_sqlite_db()
    from app.jobs.tasks import clear_stuck_generating_tests
    try:
        cleared = clear_stuck_generating_tests(max_age_seconds=settings.max_generation_time_seconds)
        if cleared:
            _log.warning("Startup: cleared %s stuck test(s)", len(cleared))
    except Exception as e:
        _log.warning("Startup: could not clear stuck tests (run: alembic upgrade head): %s", e)


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "message": "UPSC Test Engine API"}

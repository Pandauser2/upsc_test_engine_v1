"""
FastAPI application entrypoint.
APIs: auth, topics, tests. Run with: uvicorn app.main:app --reload --port 8000

API base path: routes are mounted at root (no /api/v1 prefix).
  - Auth:  POST /auth/register, POST /auth/login, GET /auth/me
  - Documents: POST /documents/upload, GET /documents, GET /documents/{id}, ...
  - Tests: POST /tests/generate, GET /tests, GET /tests/{id}/status, ...
  - Topics: GET /topics

Celery: optional; set CELERY_BROKER_URL (e.g. redis://localhost:6379/0) and run a worker to use queue.
Tenacity: LLM retries (429/5xx) are handled in app.llm.llm_service when using get_llm_service_with_fallback().
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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
    """Init SQLite DB and log LLM key status. Fail fast if production uses default SECRET_KEY."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _log = logging.getLogger("app.main")
    if (getattr(settings, "env", "") or "").strip().lower() == "production":
        if (getattr(settings, "secret_key", "") or "").strip() == "change-me-in-production":
            _log.critical("SECRET_KEY must be set in production. Set SECRET_KEY in env or .env.")
            raise RuntimeError("SECRET_KEY must be set in production. Set SECRET_KEY in env or .env.")
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
        cleared = clear_stuck_generating_tests(max_age_seconds=getattr(settings, "max_stale_generation_seconds", 1200))
        if cleared:
            _log.warning("Startup: cleared %s stuck test(s)", len(cleared))
    except Exception as e:
        _log.warning("Startup: could not clear stuck tests (run: alembic upgrade head): %s", e)
    # Fail fast if text generation pipeline deps are missing so tests don't stay "pending"
    try:
        from app.services.mcq_generation_service import generate_mcqs_with_rag  # noqa: F401
        _log.info("Generation pipeline (text: chunk + LLM) loaded OK.")
    except ImportError as e:
        _log.error("Generation pipeline import failed. Install deps (e.g. pip install -r requirements.txt). Error: %s", e)
        raise
    # Optional Celery: if broker is set and Redis is used, tasks can be enqueued via app.jobs.celery_tasks
    broker = getattr(settings, "celery_broker_url", "") or ""
    if broker.startswith("redis://"):
        try:
            from app.celery_app import celery_app
            _log.info("Celery broker configured: %s (run worker: celery -A app.celery_app worker -l info)", broker.split("@")[-1] if "@" in broker else broker)
        except Exception as e:
            _log.debug("Celery not loaded: %s", e)


@app.get("/", response_class=HTMLResponse)
def root():
    """Root: minimal page so the app 'loads' in browser; links to API docs and frontend."""
    return """
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><title>UPSC Test Engine API</title></head>
    <body style="font-family: system-ui; max-width: 600px; margin: 2rem auto; padding: 1rem;">
    <h1>UPSC Test Engine API</h1>
    <p>This is the <strong>API server</strong> (port 8000). It returns JSON, not the web app.</p>
    <ul>
    <li><a href="/docs">OpenAPI docs (Swagger)</a></li>
    <li><a href="/redoc">ReDoc</a></li>
    <li>Health: <a href="/health">/health</a></li>
    </ul>
    <p>To use the <strong>web app</strong>, run the frontend and open <strong><a href="http://localhost:3000">http://localhost:3000</a></strong>.</p>
    <pre style="background:#f0f0f0; padding: 0.5rem;">cd frontend && npm install && npm run dev</pre>
    </body>
    </html>
    """


@app.get("/health")
def health():
    """Health check (JSON)."""
    return {"status": "ok", "message": "UPSC Test Engine API"}

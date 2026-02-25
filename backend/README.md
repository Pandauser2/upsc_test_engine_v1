# UPSC Test Engine — Backend

FastAPI app (Python 3.11): auth, documents, topics, tests, MCQ generation job, .docx export.

## Setup

1. Copy `.env.example` (repo root) to `backend/.env` or set env vars.
2. **DB**: Default is SQLite (`DATABASE_URL=sqlite:///./upsc_dev.db`). Tables created on startup. For Postgres: set `DATABASE_URL`, run `docker-compose up -d` from repo root if needed, then `alembic upgrade head`.
3. Install and run:
   ```bash
   cd backend
   pip install -r requirements.txt
   alembic upgrade head   # optional for SQLite (init_sqlite_db runs at startup)
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
4. Health: `GET /health` → `{"status":"ok"}`.

## Env (see repo root `.env.example` and `app/config.py`)

- **Production:** Set `ENV=production` and `SECRET_KEY` to a secure value. The app will not start in production with the default `SECRET_KEY`.
- `DATABASE_URL` — SQLite default `sqlite:///./upsc_dev.db`; Postgres for production.
- `SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_HOURS` — Auth.
- `LLM_PROVIDER` — `claude` (default) or `openai`.
- `CLAUDE_API_KEY`, `CLAUDE_MODEL`, `CLAUDE_TIMEOUT_SECONDS` — Claude. No key → mock LLM.
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` — OpenAI when `LLM_PROVIDER=openai`.
- `PROMPT_VERSION`, `MAX_GENERATION_TIME_SECONDS`, `MIN_EXTRACTION_WORDS` — Generation.
- `UPLOAD_DIR`, `MAX_PDF_PAGES` (default 100) — Uploads.
- `EXTRACT_ON_DEMAND_TIMEOUT_SECONDS` (default 600) — Max wait for on-demand extraction in `GET /documents/{id}/extract` when text empty.
- `USE_GLOBAL_RAG`, `RAG_MIN_CHUNKS_FOR_GLOBAL` (default 20) — RAG when doc has >N chunks. See `RAG_GLOBAL_OUTLINE.md`.
- `ENABLE_EXPORT`, `EXPORTS_DIR` — Export baseline JSON. See `EXPORT_BASELINE.md`.
- `CORS_ORIGINS` — Comma-separated (default `http://localhost:3000`).

Generation: parallel single Claude calls (no Message Batches). Status from DB only; see `GENERATION_REFACTOR_STATUS.md`.

## API (all under `/`)

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `POST /documents/upload`, `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/extract`
- `GET /topics`
- `POST /tests/generate`, `GET /tests`, `GET /tests/{id}`, `GET /tests/{id}/status`, `POST /tests/{id}/cancel`, `PATCH /tests/{id}`, `PATCH /tests/{id}/questions/{qid}`, `POST /tests/{id}/questions`, `POST /tests/{id}/export`

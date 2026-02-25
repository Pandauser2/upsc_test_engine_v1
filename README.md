# UPSC Test Engine

Faculty-facing SaaS: upload UPSC coaching notes (PDF) → extraction runs in background → generate 1–20 Prelims-style MCQs (text pipeline: chunk → LLM → filter/sort). Review/edit, manual fill for partial tests, export to .docx. PDF only; no paste.

**Stack:** Next.js (App Router, TypeScript), FastAPI (Python 3.11), PostgreSQL, BackgroundTasks, abstracted LLM (OpenAI).

## Scope (Plan Steps 1–9 done)

- Backend and APIs are implemented through Step 9. Steps 10 (frontend) and 11 (Docker runbook) are planned for later.
- See **`DOCUMENTATION.md`** for API reference, configuration, and running the app; `PLAN.md` for task list and `EXPLORATION.md` for architecture and decisions.

## Quick start

1. **Start PostgreSQL** (required first): from project root run  
   `docker-compose up -d`  
   (Starts Postgres on `localhost:5432`. If you get "Connection refused" on register/login, the DB is not running.)
2. **Backend:** use the run script (uses `backend/venv` and installs deps automatically):
   ```bash
   cd backend && ./run.sh
   ```
   First time: ensure venv exists. From repo root: `python3 -m venv backend/venv`, then `cd backend && ./run.sh`.
   For DB migrations: `cd backend && ./venv/bin/alembic upgrade head` (or activate venv first and run `alembic upgrade head`).
3. Copy `.env.example` to `backend/.env` and set `DATABASE_URL`, `SECRET_KEY`, `OPENAI_API_KEY` (and optional vars).
4. Open `http://localhost:8000/docs` for Swagger.

**"No module named 'fastapi'" (macOS):** Use the run script so the correct venv is always used: `cd backend && ./run.sh`. If `venv` is missing, create it from repo root: `python3 -m venv backend/venv`, then run `cd backend && ./run.sh` again.

**Port 8000 in use (macOS):** Find process: `lsof -iTCP:8000 -sTCP:LISTEN`. Kill it: `kill $(lsof -t -iTCP:8000 -sTCP:LISTEN)`. Or start on another port: `uvicorn app.main:app --reload --port 8001`.

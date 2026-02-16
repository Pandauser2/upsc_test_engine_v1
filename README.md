# UPSC Test Engine

Faculty-facing SaaS: upload UPSC coaching notes (PDF or paste text) → generate 50 Prelims-style MCQs with answer, explanation, difficulty, and topic. Review/edit, manual fill for partial tests, export to .docx.

**Stack:** Next.js (App Router, TypeScript), FastAPI (Python 3.11), PostgreSQL, BackgroundTasks, abstracted LLM (OpenAI).

## Scope (Plan Steps 1–9 done)

- Backend and APIs are implemented through Step 9. Steps 10 (frontend) and 11 (Docker runbook) are planned for later.
- See `PLAN.md` for task list and `EXPLORATION.md` for architecture and decisions.

## Quick start

1. From project root: `docker-compose up -d` (Postgres).
2. `cd backend && pip install -r requirements.txt && alembic upgrade head && uvicorn app.main:app --reload --port 8000`.
3. Copy `.env.example` to `backend/.env` and set `DATABASE_URL`, `SECRET_KEY`, `OPENAI_API_KEY` (and optional vars).
4. Open `http://localhost:8000/docs` for Swagger.

# UPSC Test Engine — Documentation

Central reference for the UPSC Test Engine: API, configuration, running, and links to detailed docs.

---

## Overview

Faculty-facing SaaS: upload UPSC coaching notes (PDF) → background extraction → generate 1–20 Prelims-style MCQs (text pipeline: chunk → LLM → filter/sort). Review/edit, manual fill for partial tests, export to .docx.

- **Stack:** Next.js (App Router, TypeScript), FastAPI (Python 3.11), SQLite (default) or PostgreSQL.
- **Backend:** `backend/` — FastAPI app, BackgroundTasks, abstracted LLM (Claude / OpenAI).
- **Frontend:** `frontend/` — Placeholder until Step 10; API is the main interface.

---

## API Reference

**Base URL:** All routes are mounted at the server root (no `/api/v1` prefix).  
Example: `http://localhost:8000`

| Area | Method | Path | Description |
|------|--------|------|-------------|
| **Auth** | POST | `/auth/register` | Register (email, password); role `faculty`. |
| | POST | `/auth/login` | Login; returns JWT. |
| | GET | `/auth/me` | Current user (requires `Authorization: Bearer <token>`). |
| **Documents** | POST | `/documents/upload` | Upload PDF (max 100 pages); extraction in background. |
| | GET | `/documents` | List current user's documents. |
| | GET | `/documents/{document_id}` | Get one document (includes `extracted_text`). |
| | GET | `/documents/{document_id}/extract` | Extracted text; on-demand extraction if empty. |
| **Tests** | POST | `/tests/generate` | Create test (pending), enqueue generation. Body: `document_id`, `num_questions` (1–20), `difficulty`, `export_result`. |
| | GET | `/tests` | List current user's tests. |
| | GET | `/tests/{test_id}` | Test detail with questions. |
| | GET | `/tests/{test_id}/status` | Status and progress (e.g. "X/4 candidates processed"). |
| | POST | `/tests/{test_id}/cancel` | Cancel pending/generating test. |
| | PATCH | `/tests/{test_id}` | Update test (e.g. title). |
| | PATCH | `/tests/{test_id}/questions/{question_id}` | Update question. |
| | POST | `/tests/{test_id}/questions` | Add question (manual fill). |
| | POST | `/tests/{test_id}/export` | Export test to .docx. |
| **Topics** | GET | `/topics` | List topics (for tagging). |
| **Health** | GET | `/health` | Health check. |
| **Docs** | GET | `/docs` | Swagger UI. |
| | GET | `/redoc` | ReDoc. |

All document and test endpoints require authentication: `Authorization: Bearer <access_token>`.

---

## Configuration

Config is loaded from `backend/.env` (and env vars). See `backend/app/config.py` for all keys.

### Required for production

- **`ENV=production`** — Enables production checks. If set, the app **will not start** unless `SECRET_KEY` is set.
- **`SECRET_KEY`** — JWT signing. Must not be `change-me-in-production` when `ENV=production`. Set a long, random value in production.

### Database

- **`DATABASE_URL`** — Default: `sqlite:///./upsc_dev.db`. For production, use PostgreSQL (e.g. `postgresql://user:pass@host/db`). With SQLite, tables and missing columns are created/added at startup.

### Auth

- **`SECRET_KEY`** — JWT secret (required in production when `ENV=production`).
- **`JWT_ALGORITHM`** — Default `HS256`.
- **`JWT_EXPIRE_HOURS`** — Default `24`.

### LLM

- **`LLM_PROVIDER`** — `claude` (default) or `openai`.
- **Claude:** `CLAUDE_API_KEY`, `CLAUDE_MODEL`, `CLAUDE_TIMEOUT_SECONDS`. No key → mock LLM.
- **OpenAI:** `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` (when `LLM_PROVIDER=openai`).

### Generation

- **`MCQ_CANDIDATE_COUNT`** — Parallel candidates (default `4`). Progress is "X/4 candidates processed".
- **`MAX_STALE_GENERATION_SECONDS`** — Base timeout for "generating" (default 1200); dynamic per run.
- **`MIN_EXTRACTION_WORDS`** — Min words in extracted text to allow generation (default 500).

### Uploads & PDFs

- **`UPLOAD_DIR`** — Default `./uploads`.
- **`MAX_PDF_PAGES`** — Default 100; PDFs over this are rejected at upload.
- **`EXTRACT_ON_DEMAND_TIMEOUT_SECONDS`** — Max wait for on-demand extraction (default 600).

### RAG

- **`USE_GLOBAL_RAG`**, **`RAG_MIN_CHUNKS_FOR_GLOBAL`** — Global outline + RAG when chunk count &gt; threshold. See `backend/RAG_GLOBAL_OUTLINE.md`.

### Other

- **`CORS_ORIGINS`** — Comma-separated origins (default `http://localhost:3000`).
- **`DEBUG`** — If true, registration errors may expose more detail (do not use in production).

---

## Running the application

### Backend (required)

1. **Prepare environment**
   - `cd backend`
   - `python3 -m venv venv` (first time)
   - `source venv/bin/activate` (Linux/macOS) or `venv\Scripts\activate` (Windows)
   - `pip install -r requirements.txt`

2. **Configure**
   - Copy `.env.example` to `backend/.env` (or set env vars).
   - For **production:** set `ENV=production` and `SECRET_KEY` to a secure value.

3. **Database**
   - **SQLite (default):** No extra step; DB and columns are created/updated on startup.
   - **PostgreSQL:** Set `DATABASE_URL`, start Postgres (e.g. `docker-compose up -d` from repo root), then:  
     `alembic upgrade head`

4. **Start server**
   ```bash
   cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   Or use `./run.sh` if available.

5. **Verify**
   - Health: `GET http://localhost:8000/health`
   - API docs: `http://localhost:8000/docs`

### Frontend (optional)

- From repo root: `cd frontend && npm install && npm run dev` → app at `http://localhost:3000`. Currently a placeholder; APIs are used directly or via Swagger.

---

## Generation flow

1. **Upload PDF** → `POST /documents/upload`. Document status: `processing` → `ready` or `extraction_failed`.
2. **Start test** → `POST /tests/generate` with `document_id` and `num_questions` (1–20). Test created as `pending`, job enqueued.
3. **Poll progress** → `GET /tests/{test_id}/status`. While `pending`/`generating`, progress is `processed_candidates / candidate_count` (e.g. "2/4 candidates processed").
4. **Result** → Status becomes `completed`, `partial`, or `failed`; `GET /tests/{test_id}` returns test and questions.

Generation uses parallel single LLM calls (no Message Batches). Max 20 questions per test; 429 responses are retried (tenacity, up to 3 attempts).

---

## Other documentation

| Document | Description |
|----------|-------------|
| `README.md` | Project overview and quick start. |
| `backend/README.md` | Backend setup, env summary, API list. |
| `backend/SETUP_AND_RUN.md` | Step-by-step run guide (Mac). |
| `backend/RAG_GLOBAL_OUTLINE.md` | RAG and global outline. |
| `backend/GENERATION_REFACTOR_STATUS.md` | Generation pipeline (parallel, no batch). |
| `backend/EXPORT_BASELINE.md` | MCQ export baseline (JSON). |
| `EXPLORATION.md` | Architecture and design decisions. |
| `PLAN.md` | Task list and steps. |

---

*Last updated to reflect API at root, production `ENV`/`SECRET_KEY` requirement, and current generation flow.*

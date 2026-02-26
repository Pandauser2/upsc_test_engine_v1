# UPSC Test Engine — Documentation

Central reference for the UPSC Test Engine: API, configuration, running, and links to detailed docs.

---

## Overview

Faculty-facing SaaS: upload UPSC coaching notes (PDF) → background extraction → generate 1–20 Prelims-style MCQs (text pipeline: chunk → LLM → filter/sort). Review/edit, manual fill for partial tests, export to .docx.

- **Stack:** Next.js (App Router, TypeScript), FastAPI (Python 3.11), SQLite (default) or PostgreSQL.
- **Backend:** `backend/` — FastAPI app, BackgroundTasks, LLM via **Gemini only** (no Claude/OpenAI).
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
| | GET | `/documents/{document_id}` | Get one document (`extracted_text`, `total_pages`, `extracted_pages` for progress). |
| | GET | `/documents/{document_id}/extract` | Extracted text; on-demand extraction if empty. |
| **Tests** | POST | `/tests/generate` | Create test (pending), enqueue generation. Body: `document_id`, `num_questions` (1–20), `difficulty`, `export_result`. Returns **503** if `GEMINI_API_KEY` not set. |
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

### LLM (Gemini only)

- **`GEN_MODEL_NAME`** — Default `gemini-2.0-flash` (supported by current Gemini API). Use a model that supports generateContent (e.g. `gemini-2.0-flash`).
- **`GEMINI_API_KEY`** — Required for MCQ generation. If unset, `POST /tests/generate` returns **503** with message to set the key (no mock MCQs).

### Generation

- **Parallel candidates** — Fixed at 4 (Gemini). Progress is "X/4 candidates processed" (no env override).
- **`MAX_STALE_GENERATION_SECONDS`** — Base timeout for "generating" (default 1200); dynamic per run.
- **`MIN_EXTRACTION_WORDS`** — Min words in extracted text to allow generation (default 500).

### Uploads & PDFs

- **`UPLOAD_DIR`** — Default `./uploads`.
- **`MAX_PDF_PAGES`** — Default 100; PDFs over this are rejected at upload.
- **`EXTRACT_ON_DEMAND_TIMEOUT_SECONDS`** — Max wait for on-demand extraction (default 600).
- **`OCR_THRESHOLD`** — Run OCR only when native text per page < this (default 50). Set to 100 for "less than 100 character" rule. See `backend/docs/EXTRACTION_LATENCY_OPTIMIZATION.md`.

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

1. **Upload PDF** → `POST /documents/upload`. Document status: `processing` → `ready` or `extraction_failed`. While processing, GET `/documents/{id}` returns `total_pages`, `extracted_pages` ("Extracting pages X/Y").
2. **Start test** → `POST /tests/generate` with `document_id` and `num_questions` (1–20). Test created as `pending`, job enqueued.
3. **Poll progress** → `GET /tests/{test_id}/status`. While `pending`/`generating`, `progress` = `processed_candidates / 4` and `message` = `"X/4 candidates processed"` (from DB).
4. **Result** → Status becomes `completed`, `partial`, or `failed`; `GET /tests/{test_id}` returns test and questions.

Generation: 4 parallel Gemini calls (ThreadPoolExecutor), no Message Batches. Max 20 questions per test; 429/529 retried (tenacity).

---

## Parallelization

MCQ generation uses **synchronous parallel** execution: one job runs 4 LLM calls in parallel, then merges and filters results. There is no Message Batches API or async batch polling.

### Per-test parallelism (4 candidates)

- **Model:** Gemini via `google-generativeai`. One request per candidate.
- **Candidate count:** Fixed at **4**. Document chunks are split into 4 contiguous groups; each group is sent to one parallel worker.
- **Execution:** `ThreadPoolExecutor(max_workers=4)`. Each worker runs a single `generate_mcqs` call on its chunk group (with optional RAG retrieval). Workers run concurrently; completion order is not guaranteed.
- **After parallel phase:** All candidate MCQs are collected, then self-validation (critique) runs sequentially. MCQs with bad critiques are dropped; the rest are sorted (e.g. medium first) and trimmed to `target_n` (max 20).

### Progress and polling

- **DB field:** `generated_tests.processed_candidates` (0 before generation, 1–4 as each of the 4 workers finishes).
- **Update:** A progress callback runs after each worker completes (thread-safe: new DB session per update). The value is written so clients can poll without blocking the job.
- **API:** `GET /tests/{test_id}/status` returns, while status is `pending` or `generating`:
  - `progress`: `processed_candidates / 4` (0.0, 0.25, 0.5, 0.75, 1.0).
  - `message`: `"X/4 candidates processed"` (e.g. `"2/4 candidates processed"`).

### Concurrency and rate limits

- **Job-level:** A semaphore limits how many generation jobs run at once (e.g. 3). New jobs wait until a slot is free.
- **429/529 handling:** Each Gemini call is wrapped with tenacity: on 429/529 (rate limit / overloaded), retry with exponential backoff. If all retries fail, that candidate returns no MCQs; the job continues with the others and may still complete or partial.

### What is not used

- **Message Batches API:** Not used. All generation is via synchronous parallel single-request calls.
- **Config override:** The 4-candidate count is fixed in code (no env var to change it for the sync path).

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
| `backend/docs/EXTRACTION_LATENCY_OPTIMIZATION.md` | PDF extraction: OCR trigger, parallel OCR, per-page log, projected &lt;60 s. |
| `backend/docs/GEMINI_MIGRATION_STEP1.md` | Gemini-only LLM migration. |
| `EXPLORATION.md` | Architecture and design decisions. |
| `PLAN.md` | Task list and steps. |

---

*Last updated: Gemini-only LLM, extraction progress (total_pages/extracted_pages), strict OCR trigger (OCR_THRESHOLD), parallel extraction OCR.*

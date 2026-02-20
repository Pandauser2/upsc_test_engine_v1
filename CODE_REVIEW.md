# Code Review: Plan & EXPLORATION.md Alignment

**Review date:** 2025-02-15  
**Scope:** Backend (FastAPI), PLAN.md, EXPLORATION.md

---

## ✅ Looks Good

- **Logging:** Uses `logging.getLogger(__name__)` and structured log messages with context (test_id, doc_id, user_id, tokens).
- **Auth scope:** All document and test APIs use `get_current_user`; list/get/create/update are scoped by `user_id`. Topics are read-only (no auth) per design.
- **Document upload:** PDF only. Page count via PyMuPDF; >100 pages → doc `status=rejected`, 400. On accept: doc `status=processing`, extraction enqueued; when done `ready` or `extraction_failed`.
- **Test generation:** num_questions 1–20, default 15; schema rejects >20. Generation requires `doc.status=ready` and non-empty `extracted_text`; min_extraction_words enforced.
- **Partial & timeout:** Status `partial` when &lt; N questions; stuck tests marked `failed_timeout` on read and in startup cleanup.
- **Export .docx:** Three sections (Questions, Answer key, Explanations); simple format.
- **Topic slugs:** Injected via `get_topic_slugs_for_prompt`; text pipeline (mcq_generation_service → claude_impl) uses topic_slugs; post-parse maps unknown slug to default.
- **Prompt versioning:** `prompt_version` and `model` stored on GeneratedTest; from settings.
- **Config:** PROMPT_VERSION, max_generation_time_seconds=300, MAX_PDF_PAGES=100, chunk_mode, RAG, Celery broker in config and .env.example.
- **No print() / console.log:** Uses logger throughout.
- **Error handling:** HTTPException with clear detail; extraction returns ExtractionResult with is_valid/error_message; invalid PDFs flagged with fallback suggestion.
- **Types:** Python type hints used; no `any` in schemas (Pydantic models).
- **Architecture:** Services in `app/services/`, LLM in `app/llm/`, jobs in `app/jobs/`; matches EXPLORATION folder structure.

---

## ⚠️ Issues Found

### CRITICAL

- None.

### HIGH

- **[HIGH] app/jobs/tasks.py (text pipeline)** – **Done:** Generation uses extracted_text → chunk → generate_mcqs_with_rag(use_rag=False) → filter bad critique (“incorrect”/“wrong”) → simple sort (medium first) → persist up to N; partial if &lt;N. No vision path. Dedupe/rank deferred.

- **[HIGH] app/jobs/tasks.py** – **Addressed:** Elapsed check at **end** of `run_generation`: if &gt;300s, mark `failed_timeout` (passive; no mid-run abort). Stale detection on GET/startup unchanged.

### MEDIUM

- **[MEDIUM] app/llm/llm_service.py** – `get_llm_service_with_fallback()` and tenacity retries exist but generation path uses `get_llm_service()` in mcq_generation_service. Vision path is unused for generation.
  - **Fix (optional):** Use `get_llm_service_with_fallback()` in mcq_generation_service so text pipeline gets fallback + tenacity.

- **[MEDIUM] EXPLORATION §7.2 Document upload response** – Spec says `202 + doc` for POST /documents/upload. Implementation returns **201 Created**.
  - **Fix:** If product strictly requires 202 Accepted (async processing semantics), change to `status_code=status.HTTP_202_ACCEPTED`; otherwise document that 201 is used for synchronous “resource created.”

- **[MEDIUM] EXPLORATION §7.5 Jobs** – Optional `GET /jobs/{job_id}/status` (poll job status) is **not implemented**. Test status is inferred via GET /tests/{id}.
  - **Fix:** Add `GET /jobs/{job_id}/status` that returns `{ "status": "queued|started|finished|failed|failed_timeout", "result": {...} }` if you want explicit job polling (e.g. when using Celery).

### LOW

- **[LOW] app/config.py:26** – Default `secret_key: str = "change-me-in-production"` is unsafe if deployed without override.
  - **Fix:** In production, require SECRET_KEY from env (fail startup if default and not debug) or document clearly in deployment guide.

- **[LOW] EXPLORATION §10 Auth** – Spec suggests **Argon2** for password hashing; implementation uses **bcrypt**.
  - **Fix:** Optional: migrate to Argon2 for new passwords; keep bcrypt verify for existing users.

- **[LOW] EXPLORATION §10 Logging** – Spec suggests **structlog** (request_id, user_id, document_id). Standard `logging` is used.
  - **Fix:** Optional: add structlog and middleware to bind request_id/user_id to log context.

- **[LOW] POST /tests/generate response** – EXPLORATION says “test_id”; schema returns **id** (TestResponse.id). Clients can use `id` as test_id; naming is cosmetic.
  - **Fix:** If API docs promise `test_id`, add an alias or document that `id` is the test_id.

- **[LOW] PLAN Step 7 – Frontend** – Not implemented (upload warning, num_questions 1–20, partial/failed_timeout, manual fill). PLAN marks it To Do.
  - **Fix:** Implement when frontend is in scope; server already enforces limits and statuses.

---

## 📊 Summary

| Metric              | Count |
|---------------------|-------|
| Files reviewed      | 20+ (api, services, llm, jobs, config, schemas) |
| Critical issues     | 0     |
| High issues         | 2     |
| Medium issues       | 3     |
| Low issues          | 5     |

**Plan vs implementation:** Steps 1–6 and 8 are implemented; Step 7 (frontend) is intentionally not done. MVP constraints (1–20 questions, 100-page PDF limit, partial, failed_timeout, manual fill cap 20) are in place.

**EXPLORATION alignment:** PDF-only upload with extraction on upload; text pipeline (chunk → LLM → filter/sort); test generation requires ready + extracted_text; topics, export, auth scope, prompt versioning, config match. Gaps: optional jobs endpoint, Argon2/structlog; RAG deferred.

# Code Review — UPSC Test Engine (Steps 1–9)

Review of backend (FastAPI, Python) and minimal frontend (Next.js, TypeScript) implemented per PLAN.md.

---

## ✅ Looks Good

- **Logging:** Backend uses `logging.getLogger(__name__)` in `llm/openai_impl.py` and `jobs/tasks.py` with structured messages (no `print`/`console.log` in backend).
- **Error handling:** FastAPI routes use `HTTPException` with clear status and detail; auth uses 401/403; document/test endpoints scope by `current_user.id`.
- **TypeScript:** Frontend has no `any` types and no `@ts-ignore`; minimal surface (placeholder page + api base URL).
- **Secrets:** No hardcoded secrets; `config.py` uses env/defaults; `.env.example` documents required vars; default `secret_key` is explicitly "change-me-in-production".
- **Security — auth:** All document/test/topic-write flows use `Depends(get_current_user)`; documents and tests filtered by `user_id`; passwords hashed with bcrypt; JWT decode on me/protected routes.
- **Security — input validation:** Pydantic schemas validate request bodies; `RegisterRequest`/`LoginRequest` use `EmailStr`; UUID path params validated by FastAPI; question payloads now validate `correct_option` (A/B/C/D), `difficulty` (easy/medium/hard), and `options` shape (see fixes below).
- **Architecture:** Code lives in correct dirs (`app/api`, `app/services`, `app/models`, `app/llm`, `app/jobs`); single LLM abstraction; BackgroundTasks for PDF extraction and generation job.
- **Production readiness:** No TODOs or FIXMEs left in code; no debug-only branches; cost/token tracking and prompt versioning stored on `GeneratedTest`.

---

## ⚠️ Issues Found

### Fixed during review

- **[CRITICAL]** `backend/app/jobs/tasks.py` (except block) — Indentation error: `test = db.query(...)` was not indented under `try:`, causing runtime failure when marking test as failed after exception.  
  **Fix:** Indented the line under the `try` block. ✅

- **[MEDIUM]** `backend/app/api/documents.py` — PDF extraction background task caught `Exception` without logging.  
  **Fix:** Added `logger.warning("PDF extraction failed for document %s: %s", document_id, e)` before setting status failed. ✅

- **[MEDIUM]** `backend/app/schemas/test.py` — `QuestionPayload` and `QuestionPatchRequest` did not validate `correct_option`, `difficulty`, or `options` shape; invalid values could reach DB.  
  **Fix:** Added Pydantic `field_validator`s for `correct_option` (A/B/C/D), `difficulty` (easy/medium/hard), and `options` (A–D keys with string values). ✅

- **[LOW]** `backend/app/api/documents.py` & `backend/app/api/tests.py` — `limit`/`offset` for list endpoints were unbounded (DoS/abuse).  
  **Fix:** Clamp `limit` to 1–100 and `offset` to ≥ 0 in both list_documents and list_tests. ✅

### Remaining (non-blocking)

- **[LOW]** `backend/app/config.py` — Default `database_url` and `secret_key` are example values.  
  **Fix:** Ensure production uses env vars (no default secret in prod); already documented in README and `.env.example`.

- **[LOW]** `backend/app/api/tests.py` — `start_generation` uses `uuid.UUID(data.document_id)`; invalid UUID raises `ValueError` and FastAPI returns 422.  
  **Fix:** Optional: add Pydantic validator on `TestGenerateRequest.document_id` for UUID string for clearer error message.

- **[LOW]** `backend/app/services/ranking.py` — Unused import/variable: `topic_diversity_weight` parameter is accepted but not used in ranking.  
  **Fix:** Either use it in scoring or remove from signature to avoid confusion.

- **[LOW]** GET `/topics` has no auth.  
  **Fix:** Per EXPLORATION, topic list is read-only and shared; keeping it public is acceptable. Add auth later if needed.

---

## 📊 Summary

| Metric            | Count |
|-------------------|--------|
| Files reviewed    | 25+ (backend app/, frontend src/) |
| Critical issues   | 1 (fixed: indentation in tasks.py) |
| High issues       | 0 |
| Medium issues     | 2 (fixed: PDF extraction logging, question schema validation) |
| Low issues        | 2 (fixed: list limit/offset bounds; 3 remaining: config defaults, UUID validator, ranking param) |

**Verdict:** Backend and minimal frontend are in good shape for the current scope. One critical bug (indentation in the generation job’s exception handler) was fixed; logging, validation, and list bounds were improved. Remaining items are low priority and can be handled in a follow-up.

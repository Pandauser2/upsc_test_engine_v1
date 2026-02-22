# MCQ Parallel + Batch Implementation — Status Report

**Note:** Message Batches were removed. Current behavior: parallel single Claude calls for all N=1–20; no `batch_id`; status from DB only. See `../GENERATION_REFACTOR_STATUS.md`. This report describes the prior implementation.

## Files changed

| File | Change summary |
|------|----------------|
| `app/models/generated_test.py` | Added `batch_id: Mapped[str \| None]`, `questions_generated: Mapped[int] = 0` |
| `app/config.py` | Added `mcq_candidate_count: int = 4` (env: `MCQ_CANDIDATE_COUNT`) |
| `app/schemas/test.py` | `TestGenerateRequest.num_questions` validated 1–20; added `TestStatusResponse` |
| `app/services/mcq_generation_service.py` | `perf_counter` timing; `target_n` param; ≤5 → `ThreadPoolExecutor(max_workers=4)`; >5 → `_submit_mcq_batch` → return `batch_id`; 5-tuple return |
| `app/llm/claude_impl.py` | `build_batch_request_for_mcqs`, `submit_mcq_batch`, `get_batch_status`, `get_batch_results`, `_fetch_batch_results_via_url` |
| `app/jobs/tasks.py` | `_get_candidate_count()`; `run_generation` handles `batch_id` (set test.batch_id, questions_generated=0, status=generating, return); `poll_batch_generations()`, `_process_one_batch_test()` |
| `app/api/tests.py` | `GET /tests/{test_id}/status` → `TestStatusResponse`; calls `poll_batch_generations()` |
| `app/database.py` | SQLite init: add `batch_id`, `questions_generated` to `generated_tests` if missing |
| `alembic/versions/005_questions_generated_batch_id.py` | Migration: add `batch_id`, `questions_generated` |

## Key functions modified/added

- **generate_mcqs_with_rag** — Returns `(mcqs, scores, inp, out, batch_id)`. Path A: target_n>5 → batch submit. Path B: ThreadPoolExecutor(4) + validation loop. Logs: candidate loop time, validation loop time, total time.
- **run_generation** — Unpacks 5-tuple; if `batch_id`: set test.batch_id, questions_generated=0, status=generating, commit, return. Else: existing persist flow.
- **poll_batch_generations** — Loads tests with batch_id and status=generating; for each, get_batch_status → if ended/complete, get_batch_results → parse, filter, persist Questions, set questions_generated and status.
- **get_test_status** — Calls poll_batch_generations(); returns status, progress, message, questions_generated, target_questions.

## Manual steps

1. **Env (optional):** `MCQ_CANDIDATE_COUNT=4` (default 4). `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` for real + batch API.
2. **Migration:**  
   - **PostgreSQL / fresh Alembic:** `cd backend && alembic upgrade head`  
   - **Existing SQLite created via app:** No migration needed; `init_sqlite_db()` at startup adds `batch_id` and `questions_generated` if missing.  
   - **SQLite + first-time Alembic:** If DB was created by `Base.metadata.create_all`, stamp then upgrade: `alembic stamp 004 && alembic upgrade head`.
3. **Batch API:** Batches require a valid Anthropic API key; mock LLM does not submit batches (batch path only when `get_llm_service()` returns `ClaudeLLMService`).

## Potential gotchas

- **Batch status:** Anthropic may use `processing_status in ("ended", "completed", "succeeded", "complete")`; if your API returns another value, add it in `_process_one_batch_test`.
- **results_url:** Batch results are fetched via `results_url` (httpx). If the URL requires auth, the SDK might need to use an authenticated client for that GET; current code uses plain `httpx.get(url)`.
- **Polling trigger:** Progress is updated only when something calls `poll_batch_generations()` (e.g. GET `/tests/{test_id}/status`). For true 30s polling without user action, add a background scheduler (e.g. APScheduler) or Celery beat that calls `poll_batch_generations()` every 30s.
- **Parallel path (≤5):** Still uses Sonnet; 4 workers run concurrently so token usage is unchanged but wall-clock drops.

---

## Quick local test commands

**1. Start server and ensure DB has new columns (SQLite init runs on startup):**
```bash
cd upsc-test-engine/backend
source venv/bin/activate   # or: . venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**2. Generate N=3 (parallel path, no batch):**  
- POST `/tests/generate` with body `{"document_id": "<ready-doc-uuid>", "num_questions": 3}`.  
- Expect 202; then GET `/tests/{test_id}/status` until `status` is `completed` or `partial`.  
- Response: `progress`, `message` e.g. `"3 of 3 questions created"`.

**3. Generate N=10 (batch path if Claude + key set):**  
- POST `/tests/generate` with `"num_questions": 10`.  
- Expect 202; test will have `status=generating` and `batch_id` set.  
- Poll GET `/tests/{test_id}/status` every 10–30s; each call runs `poll_batch_generations()`.  
- When batch finishes, progress goes to 1.0 and status to `completed` or `partial`.

**4. Validation (max 20):**  
- POST `/tests/generate` with `"num_questions": 21` → 400 (schema validation).

Example with curl (replace JWT and ids):
```bash
# Login, then:
export TOKEN="<your-jwt>"
export DOC_ID="<document-uuid-with-status-ready>"
curl -s -X POST "http://localhost:8000/tests/generate" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"num_questions\": 3}" | jq .
# Use test id from response:
export TEST_ID="<test-uuid>"
curl -s "http://localhost:8000/tests/$TEST_ID/status" -H "Authorization: Bearer $TOKEN" | jq .
```

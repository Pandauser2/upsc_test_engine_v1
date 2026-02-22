# Generation refactor: Message Batches removed, parallel single calls only

## Goal
Make all jobs (N=1–20) **fast and reliable** without quality loss: remove Anthropic Message Batches, use **parallel single Claude calls** for all `target_n`, keep Sonnet. No more stuck jobs at 0 questions.

---

## Files changed

| File | Changes |
|------|--------|
| `app/services/mcq_generation_service.py` | Removed batch path (`target_n > 5` → Message Batches). All `target_n` now use `ThreadPoolExecutor(max_workers=4)` parallel single `generate_mcqs` calls. Removed `_submit_mcq_batch`. Return type unchanged: `(mcqs, scores, inp, out, None)`. |
| `app/llm/claude_impl.py` | Removed `build_batch_request_for_mcqs`, `submit_mcq_batch`, `get_batch_status`, `get_batch_results`, `_fetch_batch_results_via_url`. Kept single `generate_mcqs` and `_parse_mcqs_json`. Added **429 retry**: `@retry` with `retry_if_exception(_is_rate_limit)`, `wait_exponential(multiplier=1, min=1, max=8)`, 4 attempts. |
| `app/jobs/tasks.py` | Removed `batch_id` handling (no early return on batch submit). Removed `poll_batch_generations`, `_process_one_batch_test`, `POLL_BATCH_INTERVAL_SECONDS`. After persisting questions, set `test.questions_generated = len(mcqs)`. Removed unused `Any` import. |
| `app/api/tests.py` | Removed `poll_batch_generations` from imports and from `get_test_status` and `get_test`. **GET /tests/{id}/status**: no polling; reads only from DB. When `status` is `pending`/`generating` and `target > 0`, message is **"Generating... usually under 1 minute. 0 of N questions created"**; otherwise `"X of N questions created"`. |
| `app/models/generated_test.py` | Removed `batch_id` column from model. |
| `app/database.py` | In `init_sqlite_db`, removed the block that added `batch_id` if missing (so new/fresh SQLite no longer get `batch_id`). |
| `alembic/versions/006_drop_batch_id.py` | **New migration**: `upgrade()` drops `batch_id` from `generated_tests`; `downgrade()` adds it back. |
| `tests/test_pipeline_integration.py` | Comment update: `batch_id is None` → "parallel single calls only (no Message Batches)". |

---

## Key diffs summary

- **Generation path**: One path only — chunk → up to 4 parallel `generate_mcqs` (by chunk groups) → collect → validate → filter/sort → persist. No batch submit, no polling.
- **Status**: `pending` → `generating` (when job starts) → `completed` or `partial` when done. `questions_generated` is 0 until the job finishes, then set to number of questions persisted.
- **Status endpoint**: Pure read from DB; progress = `questions_generated / target_questions`; UX message for generating: *"Generating... usually under 1 minute. 0 of N questions created"*.
- **429**: Claude `generate_mcqs` is wrapped with tenacity retry (1–8 s exponential, 4 attempts) so transient rate limits are retried.

---

## Manual steps

1. **Run migration 006** (after 005 is applied):
   ```bash
   cd backend && ./venv/bin/python -m alembic upgrade head
   ```
   If your DB is already at revision 005, this will only run 006 and drop `batch_id`. If you hit errors on earlier revisions (e.g. UUID vs SQLite), fix or run from your current revision.

2. **Restart the API** so all in-memory batch logic is gone.

3. **Optional**: Clear any tests stuck in `generating` with old `batch_id` (they will now have no `batch_id` column after 006; status can stay `generating` until cleared by `clear_one_stuck_test_if_stale` when user hits GET list/detail, or restart runs `clear_stuck_generating_tests`).

---

## Test commands

- **Pipeline integration (mock LLM)**:
  ```bash
  cd backend && ./venv/bin/python -m pytest tests/test_pipeline_integration.py -v --tb=short
  ```

- **Generate N=3 (sync-style, few chunks)**:
  ```bash
  # POST /tests/generate with num_questions=3, then GET /tests/{id}/status until status=completed
  curl -X POST 'http://127.0.0.1:8000/tests/generate' -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
    -d '{"document_id":"<doc_id>","num_questions":3,"difficulty":"MEDIUM"}'
  # Poll: GET /tests/{test_id}/status
  ```

- **Generate N=12 (parallel, multiple chunk groups)**:
  ```bash
  # Same as above with num_questions=12; expect "Generating... usually under 1 minute" then completion in well under 1 min (no batch delay).
  ```

- **Check latency and status**:
  - After POST, poll GET `/tests/{test_id}/status`: `message` should show "Generating... usually under 1 minute. 0 of N questions created" until job completes, then "N of N questions created" with `status: completed` or `partial`.
  - No more 15+ minute waits or stuck at 0 questions from Message Batches.

---

## Summary

- **Removed**: All Message Batch code (submit, poll, get_batch_status/results, batch_id in DB and model).
- **Single path**: Parallel single Claude calls (4 workers) for N=1–20; collect → validate → persist in `run_generation`; set `questions_generated` at end.
- **UX**: Status endpoint is read-only; message for N>0 generating: *"Generating... usually under 1 minute. 0 of N questions created"*.
- **Reliability**: 429 retry (tenacity 1–8 s, 4 attempts) on `generate_mcqs`; no dependency on batch API latency or polling.

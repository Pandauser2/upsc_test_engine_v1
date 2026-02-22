# Code Review: MCQ Parallel + Batch Implementation

**Note:** Message Batches were removed. Current behavior: parallel single Claude calls for all N=1–20; status from DB only. See `../GENERATION_REFACTOR_STATUS.md`. This doc describes the prior batch-based design.

## ✅ Looks Good

- **Logging:** Uses `logger` (e.g. `logger.info`, `logger.warning`, `logger.debug`) with context (test_id, batch_id, elapsed time). No `print()` or `console.log`.
- **Error handling:** Try/except in `_submit_mcq_batch`, `_process_one_batch_test`, `get_batch_status`, `get_batch_results`; exceptions logged and return None/empty; run_generation marks test failed on error.
- **Production readiness:** No hardcoded secrets; API key from settings/env. No TODOs or debug-only code in the new paths.
- **Architecture:** Follows existing patterns (get_llm_service, SessionLocal, _mark_failed); code in correct modules (services, llm, jobs, api).
- **Security:** Auth via `get_current_user` on status and generate endpoints; target_questions validated 1–20 in schema.
- **Types:** Python type hints used (tuple return, Optional, list[dict]); no `any` in new code; `Any` only for llm parameter in _process_one_batch_test (duck-typed).

## ⚠️ Issues Found & Fixed

- **[HIGH] [app/services/mcq_generation_service.py]** — `UnboundLocalError`: inner `from app.llm import get_llm_service` in `if target_n > 5` made `get_llm_service` local for the whole function, so Path B raised when calling `get_llm_service()`.
  - **Fix:** Removed the redundant inner import; use module-level `get_llm_service` in both paths.

- **[MEDIUM] [app/jobs/tasks.py]** — `_process_one_batch_test` could add `Question` rows with `topic_id=None` when `default_topic_id` was missing, risking FK violation or bad data.
  - **Fix:** If `default_topic_id` is still None after loading topic_list, call `_mark_failed(db, test, "No topic_list rows (batch completion)")`, clear `batch_id`, commit, and return.

- **[LOW] [tests/test_pipeline_integration.py]** — Test unpacked 4 values from `generate_mcqs_with_rag`; return type is now 5-tuple.
  - **Fix:** Unpack `mcqs, scores, inp, out, batch_id` and add `assert batch_id is None` for the sync path.

## 📊 Summary

- **Files reviewed:** 9 (models, config, schemas, mcq_generation_service, claude_impl, tasks, api/tests, database, migration).
- **Critical issues:** 0 (after fixes).
- **Warnings fixed:** 2 (UnboundLocalError, None topic_id); 1 test update (5-tuple).

## Tests

- **tests/test_pipeline_integration.py:** All 4 tests pass (including `test_full_pipeline_chunking_to_rag_mock_llm` with 5-tuple and `batch_id is None`).
- **tests/test_chunking.py:** All 7 pass.
- **tests/test_pdf_extraction.py:** 3 failures are pre-existing (short-text is_valid, fake_ocr signature, monkeypatch). Not caused by MCQ parallel/batch changes; left as-is to avoid changing architecture.

## No Change / Out of Scope

- PDF extraction logic and its tests (separate feature).
- Batch `results_url` auth (Anthropic may require authenticated GET; current code uses plain httpx.get).
- Adding a 30s scheduler for `poll_batch_generations()` (documented as optional; status endpoint currently triggers polling).

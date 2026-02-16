# Peer Review: Verification and Actions

## Valid findings (confirmed and fixed)

1. **Dedup threshold too low; normalize tokens**
   - **Verified:** Thresholds were 0.45 Jaccard / 0.5 overlap; tokenization did not strip input.
   - **Changes:** Raised to 0.55 / 0.55 (constants in `app/services/dedupe.py`); `_tokenize()` now uses `s.strip().lower()` and guards for empty/non-string. Option-overlap threshold kept at 0.45.

2. **Real topic diversity**
   - **Verified:** `select_top_with_topic_diversity()` was `return mcqs[:n]` with no bucketing.
   - **Changes:** In `app/services/ranking.py`: bucket by `topic_tag` (normalized), sort topic slugs for deterministic order, round-robin from buckets until `n` selected.

3. **Hard 300s timeout**
   - **Verified:** Loop already checked `_elapsed(start) > ...`; no per-request timeout on OpenAI.
   - **Changes:** All timeout checks use `>=` for strict cap; `app/llm/openai_impl.py`: `timeout=60.0` on MCQ generation, `timeout=30.0` on validation so no single request hangs indefinitely.

4. **50-question cap (manual add)**
   - **Verified:** `POST /tests/{id}/questions` did not reject when test already had 50 questions.
   - **Changes:** In `app/api/tests.py`, before inserting: `current_count = db.query(Question).filter(...).count()`; if `current_count >= 50` return 400 with message "Test already has 50 questions; cap enforced."

5. **Normalize difficulty before persisting**
   - **Verified:** Job used `m.get("difficulty", "medium")` with no lower/strip; LLM could return "Medium" or " medium ".
   - **Changes:** In `app/jobs/tasks.py`: `raw_diff = (m.get("difficulty") or "medium").strip().lower()`; map to `easy`|`medium`|`hard` else `"medium"`. Also normalize `question`, `explanation`, `correct_option` (via `_normalize_correct_option()` for A/B/C/D), and `validation_result` before persist.

6. **Replace wildcard CORS**
   - **Verified:** `main.py` had `allow_origins=["*"]`.
   - **Changes:** `app/config.py`: added `cors_origins: str = "http://localhost:3000"` (comma-separated). `main.py`: parse `settings.cors_origins`, use list for `allow_origins`; fallback to `["http://localhost:3000"]` if empty. `.env.example`: added `CORS_ORIGINS=http://localhost:3000`.

---

## Invalid / already-handled findings

7. **DB session closes in background task**
   - **Verified:** Both background tasks close the session. `documents._run_pdf_extraction`: `try/finally` with `db.close()`. `jobs.tasks.run_generation`: `try/except/finally` with `db.close()` in `finally`. No change made.

8. **Use real token usage from OpenAI**
   - **Verified:** `app/llm/openai_impl.py` already uses `response.usage.prompt_tokens` and `response.usage.completion_tokens`; no manual token estimation. `tasks.py` accumulates `total_input += ti`, `total_output += to`. No change made.

---

## Summary

- **6 findings** implemented (dedup, topic diversity, timeout, 50 cap, difficulty normalization, CORS).
- **2 findings** closed as already correct (DB session close, real OpenAI token usage).

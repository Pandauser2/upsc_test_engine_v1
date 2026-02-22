# MCQ Generation: Parallel + Message Batches Implementation

**Note:** Message Batches were removed. All N=1–20 now use parallel single Claude calls; no batch_id, no polling. See `../GENERATION_REFACTOR_STATUS.md`. This doc describes the prior design.

## Summary

- **target_n ≤ 5:** Parallel single calls via `ThreadPoolExecutor(max_workers=4)`.
- **target_n > 5:** Anthropic Message Batches (4 requests), return `batch_id`; progress via polling.
- **Cap:** Max 20 questions; API rejects `num_questions` > 20 (400).
- **Candidates:** Config `mcq_candidate_count` = 4 (workers / batch request count); total questions requested = `target_n + 2` (buffer for validation drop).
- **Progress:** `GET /tests/{test_id}/status` returns `{ status, progress, message, questions_generated, target_questions }`. Each call triggers `poll_batch_generations()` so batch results are processed when the client polls.

---

## Latency & cost projection

| Scenario | Before (sequential) | After (parallel / batch) |
|----------|----------------------|---------------------------|
| **4 questions** | 4 × (gen + validate) ≈ 4 × ~8s = ~32s | 4 parallel gen + sequential validate ≈ ~10–12s |
| **15 questions** | Many sequential batches ≈ 60–90s | Batch: 4 requests in one batch → poll when ended; no blocking. Per-request cost unchanged; total wall-clock lower. |
| **Cost** | Same token usage | Same (Sonnet); batch API may have different pricing; check Anthropic batch docs. |

- **Before:** One LLM call per batch of chunks (batch_size=3), then one validate_mcq per MCQ; all sequential.
- **After (≤5):** Up to 4 chunk-batches in parallel (gen), then sequential validation. **After (>5):** 4 batch requests submitted once; results processed when batch ends (polling); no per-MCQ validation in batch path (all parsed MCQs kept until filter).

---

## Affected files / DB

| File | Changes |
|------|---------|
| `app/config.py` | `mcq_candidate_count: int = 4` |
| `app/jobs/tasks.py` | `_get_candidate_count()`, `run_generation` returns early when `batch_id`; `poll_batch_generations()`, `_process_one_batch_test()`; `POLL_BATCH_INTERVAL_SECONDS` |
| `app/services/mcq_generation_service.py` | `time.perf_counter` timing; `target_n` param; path A: `_submit_mcq_batch` when target_n>5; path B: `ThreadPoolExecutor(max_workers=4)`; return 5-tuple `(..., batch_id \| None)` |
| `app/llm/claude_impl.py` | `build_batch_request_for_mcqs`, `submit_mcq_batch`, `get_batch_status`, `get_batch_results`; `_fetch_batch_results_via_url` (httpx get results_url jsonl) |
| `app/models/generated_test.py` | `batch_id`, `questions_generated` |
| `app/api/tests.py` | `GET /tests/{test_id}/status` → `TestStatusResponse`; `poll_batch_generations()` on status; validation already 1–20 |
| `app/schemas/test.py` | `TestStatusResponse(status, progress, message, questions_generated, target_questions)` |
| `app/database.py` | SQLite fallback: add `batch_id`, `questions_generated` if missing |
| `alembic/versions/005_questions_generated_batch_id.py` | Add `batch_id`, `questions_generated` to `generated_tests` |

---

## Minimal code diffs (conceptual)

**Parallel block (target_n ≤ 5):**
```python
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(_one_batch, start): start for start in range(0, len(chunk_list), batch_size_use)}
    for fut in as_completed(futures):
        mcqs, inp, out = fut.result()
        total_inp += inp; total_out += out; all_mcqs.extend(mcqs)
```

**Batch submit (target_n > 5):**
```python
batch_id = llm.submit_mcq_batch(requests)  # 4 requests from _submit_mcq_batch
return [], [], 0, 0, batch_id
```

**Polling loop:**  
`poll_batch_generations()` loads tests with `batch_id` and `status=generating`; for each, `get_batch_status`; if ended, `get_batch_results` → parse MCQs → filter → persist → set `questions_generated`, `status=completed|partial`, `batch_id=None`.

**Status endpoint:**
```python
@router.get("/{test_id}/status", response_model=TestStatusResponse)
def get_test_status(...):
    poll_batch_generations()
    # ... load test, return status, progress=questions_generated/target_n, message
```

---

## Suggested unit tests

1. **Parallel safety:** Mock `get_llm_service().generate_mcqs` to return fixed MCQs; call `generate_mcqs_with_rag` with target_n=5; assert all 4 workers are used (e.g. call count) and result is merged without duplicates/races.
2. **Batch parsing:** With a fixture jsonl (one line per batch result), assert `get_batch_results` or `_fetch_batch_results_via_url` returns list of (custom_id, raw_text, inp, out); assert `_parse_mcqs_json` on raw_text yields expected MCQ count.
3. **Validation:** POST `/tests/generate` with `num_questions=21` → 400. GET `/tests/{id}/status` returns progress in [0, 1] and message "X of Y questions created".

---

## Execution plan

**Single phase (app + DB):**

1. Run migration: `alembic upgrade head` (or rely on SQLite init for dev).
2. Deploy app; ensure `ANTHROPIC_API_KEY` (or `CLAUDE_API_KEY`) is set for batch API.
3. Frontend: poll `GET /tests/{test_id}/status` every 30s when status is `pending` or `generating`; show `progress` and `message` ("X of Y questions created").

**Optional two-phase:**

1. **Phase 1:** Migration + model + status endpoint + polling logic; keep generation sync only (no batch path) to validate DB and status.
2. **Phase 2:** Enable batch path in `generate_mcqs_with_rag` (target_n > 5 → submit batch, return batch_id) and `poll_batch_generations` to process results.

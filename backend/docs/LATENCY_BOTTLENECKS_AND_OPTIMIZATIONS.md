# Latency bottlenecks and optimizations (100-page PDF, N=10)

Analysis for the sync parallel generation path: 100-page PDF, target 10 questions. Includes perf_counter instrumentation added, estimated timings, proposed optimizations, risks, and a phased plan.

---

## 1. Instrumentation added (perf_counter)

### app/services/mcq_generation_service.py

| Phase | Log / variable | Where |
|-------|-----------------|--------|
| **Chunking** | `elapsed_chunk` | After `chunk_text()`; log: `chunking %.2fs chunks=%s` |
| **FAISS build** | `elapsed_faiss` | After `build_faiss_index()`; log: `FAISS build %.2fs (use_rag=%s)` |
| **Parallel block** | `elapsed_parallel` | Around `ThreadPoolExecutor` + `as_completed`; log: `parallel block %.2fs (candidates=%s) mcqs=%s` |
| **Each generate_mcqs** | Per-candidate | Inside `_one_candidate`: log `generate_mcqs candidate=%s %.2fs mcqs=%s` on success; on exception log elapsed |
| **Validation loop** | `elapsed_val` | Around sequential `validate_mcq` loop; log: `validation loop %.2fs (mcqs=%s)` |
| **Total** | `elapsed_total` | From `t0`; summary log: `total %.2fs (chunk=... faiss=... parallel=... validation=...)` |

### app/jobs/tasks.py

| Phase | Log | Where |
|-------|-----|--------|
| **Chunking (outline)** | `chunking (outline) %.2fs chunks=%s` | After first `chunk_text()` used for outline / RAG decision |
| **Outline** | Existing `outline %.2fs` | Global RAG outline generation (summarize + generate_global_outline) |
| **generate_mcqs_with_rag** | Existing `generate_mcqs_with_rag %.2fs` | Full service call |
| **Dedupe/rank** | `dedupe/rank %.2fs (filtered to %s)` | Filter bad critique → `_sort_medium_first` → `[:target_n]` |

### app/llm/claude_impl.py

| Phase | Log | Where |
|-------|-----|--------|
| **generate_mcqs API** | `Claude generate_mcqs API %.2fs` | Around `_create()` (single Messages API call) |

---

## 2. Latency breakdown (100-page PDF, N=10)

Rough character count: ~100 pages × ~3–4k chars/page → ~350k chars. Chunking (semantic, 1500 chars, 0.2 overlap) yields ~80–120 chunks. Global RAG: chunks > 20 → outline + FAISS.

### Current pipeline (order of execution)

1. **tasks: chunking (outline)** — One `chunk_text()` for outline. ~2–5 s for 80–120 chunks (spaCy/semantic).
2. **tasks: outline** — Summarize up to 10 chunks + generate_global_outline. ~15–40 s (2× LLM calls if enabled).
3. **mcq_generation_service: chunking** — Second `chunk_text()` on same text. ~2–5 s (duplicate work; could reuse).
4. **mcq_generation_service: FAISS build** — Embed 80–120 chunks, build index. ~5–15 s (sentence-transformers + faiss).
5. **mcq_generation_service: parallel block** — 4 × `generate_mcqs` (each ~3 Qs for N=10). Wall time ≈ max of 4 calls. Per call ~20–45 s (depends on context length). **Bottleneck:** ~25–45 s wall.
6. **mcq_generation_service: validation loop** — Sequential `validate_mcq` for ~12–15 MCQs. **Bottleneck:** 12–15 × ~3–8 s ≈ **36–120 s**.
7. **tasks: dedupe/rank** — In-memory filter + sort + slice. &lt;0.1 s.

### Estimated current total (100-page, N=10)

| Phase | Low (s) | High (s) |
|-------|---------|----------|
| Chunking (outline) | 2 | 5 |
| Outline (global RAG) | 15 | 40 |
| Chunking (service) | 2 | 5 |
| FAISS build | 5 | 15 |
| Parallel generate_mcqs (wall) | 25 | 45 |
| Validation loop | 36 | 120 |
| Dedupe/rank | 0 | 0.1 |
| **Total** | **~85** | **~230** |

Dominant cost: **validation loop** (sequential N_candidates × 4 × n_per_candidate ≈ 12–15 validations), then **parallel block** (4 Sonnet calls), then **outline** if enabled.

---

## 3. Proposed optimizations

### A. Batch 2–3 questions per Sonnet call (fewer parallel calls)

- **Idea:** Ask for 3–4 MCQs per request and use 2–3 parallel workers instead of 4 × ~3. Same total MCQs, fewer API round-trips.
- **Change:** In `generate_mcqs_with_rag`: e.g. `PARALLEL_CANDIDATES = 3`, `n_per_candidate = ceil(10/3) = 4`. Or 2 candidates × 5 Qs each.
- **Prompt:** In `claude_impl.generate_mcqs`, prompt already supports variable `n`; ensure "Generate exactly {n} MCQs" and JSON shape are clear for n=4–5.
- **Effect:** Slightly fewer concurrent calls → may reduce 429 risk; wall time of parallel block ≈ max of 2–3 calls (each call slightly longer for more Qs). **Rough saving:** 5–15 s (one fewer slowest call).
- **Affected:** `mcq_generation_service.py` (PARALLEL_CANDIDATES, n_per_candidate), `tasks.py` (processed_candidates = 3), status API ("X/3 candidates").

### B. Skip per-candidate critique when quality holds

- **Idea:** If we trust generation quality (e.g. after A/B or sampling), add a flag to skip the sequential `validate_mcq` loop and set a default `validation_result` (e.g. "Skipped (fast path)").
- **Change:** e.g. `skip_validation: bool = False` in `generate_mcqs_with_rag`; when True, do not call `llm.validate_mcq`, attach a constant critique/score.
- **Effect:** Removes **36–120 s** from the hot path. **Largest single gain.**
- **Risk:** Quality regression if bad keys/explanations slip through. Mitigation: A/B test (see below).
- **Affected:** `mcq_generation_service.py` (generate_mcqs_with_rag), optionally `tasks.py` (pass flag from metadata/settings).

### C. Global RAG fallback

- **Idea:** For 100-page docs, outline + FAISS add 20–55 s. Option to skip global RAG (no outline, no FAISS) and give full chunked text to fewer, larger calls.
- **Change:** e.g. `use_global_rag=False` when `num_questions <= 10` or when a "fast path" is requested; or cap outline chunks / skip outline and only use FAISS on a subset of chunks.
- **Effect:** Saves **20–55 s** (outline + FAISS) at the cost of less targeted retrieval. Quality may drop for very long docs.
- **Affected:** `tasks.py` (use_global_rag / outline logic), `mcq_generation_service.py` (use_rag=False or no outline).

---

## 4. Projected timings (target &lt;120 s)

| Scenario | Chunk | Outline | FAISS | Parallel | Validation | Dedupe | Total |
|----------|-------|---------|-------|----------|------------|--------|-------|
| **Current** | ~4 | ~25 | ~10 | ~35 | ~70 | ~0 | **~144** |
| **After B (skip validation)** | ~4 | ~25 | ~10 | ~35 | 0 | ~0 | **~74** |
| **After B + C (skip validation, no global RAG)** | ~4 | 0 | 0* | ~40 | 0 | ~0 | **~44** |
| **After A + B (3 candidates, skip validation)** | ~4 | ~25 | ~10 | ~30 | 0 | ~0 | **~69** |

\* With no RAG, service still chunks and can build FAISS; "no global RAG" here means skip outline + skip or simplify FAISS for fast path.

Target **&lt;120 s** is achievable with **B (skip validation)** or **B + C**. &lt;60 s is plausible with B + C.

---

## 5. Risks and A/B test

- **Quality regression (skip validation):** Bad keys or explanations may not be filtered. Mitigation: run a **A/B test**: 50% of generations with validation, 50% without; compare post-hoc human or rule-based quality (e.g. report "correct key" / "explanation consistent") and latency. Store in DB: `generation_metadata.skip_validation = true/false` and a quality score if available.
- **Quality regression (no global RAG):** Long documents may get less relevant context per call. Mitigation: limit "fast path" to e.g. `num_questions <= 10` and doc size &lt; 50 pages, or A/B by document size.
- **429 / rate limits:** Fewer parallel calls (A) slightly reduce burst load; batching more Qs per call (A) keeps total tokens similar.

---

## 6. Minimal code diffs (illustrative)

### Phase 1: Optional skip validation (largest gain)

**app/services/mcq_generation_service.py**

- Add parameter: `skip_validation: bool = False`.
- In the validation block: if `skip_validation`, loop over `all_mcqs` and set `m["validation_result"] = "Skipped (fast path)"`, `scores.append(0.7)` (or 0.5), and set `m["quality_score"]`; do not call `llm.validate_mcq`. Keep `elapsed_val` and log it as 0 or "skipped".

**app/jobs/tasks.py**

- Read `skip_validation` from `test.generation_metadata` or `settings` (e.g. `SKIP_VALIDATION_FAST_PATH=true`).
- Pass `skip_validation` into `generate_mcqs_with_rag`.
- Dedupe/rank still runs (filter by BAD_CRITIQUE_SUBSTRINGS; "Skipped" does not match, so all MCQs kept).

**app/llm/claude_impl.py**

- No change required for Phase 1.

### Phase 2 (optional): Batch 2–3 Qs per call (fewer calls)

**app/services/mcq_generation_service.py**

- Reduce `PARALLEL_CANDIDATES` to 3 (or 2). Compute `n_per_candidate = max(1, (num_questions + candidate_count - 1) // candidate_count)` (already present).
- Ensure prompt in claude_impl supports n=4–5 (already uses `n`).

**app/llm/claude_impl.py**

- Optional prompt tweak: e.g. "Generate exactly {n} MCQs. Output valid JSON only: {\"mcqs\": [ ... ]}" to reinforce batch size. No structural change.

**app/jobs/tasks.py**

- `processed_candidates = 3` (or 2); status message "X/3 candidates processed".

**app/api/tests.py**

- For generating status, use `candidate_count = 3` (or from a constant shared with tasks).

---

## 7. Affected functions

| File | Functions / constants |
|------|------------------------|
| **mcq_generation_service.py** | `generate_mcqs_with_rag` (skip_validation param, validation branch), `_one_candidate`, `PARALLEL_CANDIDATES` |
| **tasks.py** | `run_generation` (chunking log, dedupe log, pass skip_validation, PARALLEL_CANDIDATES / processed_candidates) |
| **claude_impl.py** | `generate_mcqs` (per-call timing already added; optional prompt tweak for n=4–5) |
| **api/tests.py** | Status handler (candidate_count if Phase 2) |

---

## 8. Phased plan

**Phase 1 (target &lt;120 s, low risk)**  
1. Add and keep the perf_counter logging (chunking, FAISS, parallel block, each generate_mcqs, validation, dedupe/rank, API timing).  
2. Introduce `skip_validation` (metadata or setting) and fast path in `generate_mcqs_with_rag`.  
3. Run A/B: 50% with validation, 50% without; log `skip_validation` and latency in DB; compare quality on a sample.  
4. If quality is acceptable, enable skip_validation by default for e.g. N≤10 or a "fast" profile.

**Phase 2 (optional, further reduction)**  
1. Reduce to 3 (or 2) parallel candidates and 3–4 (or 5) Qs per Sonnet call.  
2. Optional: global RAG fallback (skip outline/FAISS for "fast" path or N≤10).  
3. Update status API and messages to "X/3 candidates".  
4. Re-run latency tests and A/B for quality.

---

*Document generated from analysis of mcq_generation_service.py, tasks.py, and claude_impl.py. Perf_counter instrumentation is in place; optimizations are proposed and not yet implemented.*

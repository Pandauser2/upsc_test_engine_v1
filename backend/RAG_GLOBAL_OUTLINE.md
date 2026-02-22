# RAG + global outline (gated)

Global outline and RAG retrieval are **off by default**. They are enabled only when **USE_GLOBAL_RAG=true** and the document has **more than RAG_MIN_CHUNKS_FOR_GLOBAL** chunks (default 9 → i.e. 10+ chunks). This protects small-job latency (short PDFs skip outline + FAISS).

## Gating logic

1. After chunking: `num_chunks = len(chunks)`.
2. **If** `USE_GLOBAL_RAG` is true **and** `num_chunks > RAG_MIN_CHUNKS_FOR_GLOBAL` (default 9):
   - Compute chunk summaries (up to `rag_outline_max_chunks`) → `generate_global_outline` → pass `global_outline` and `use_rag=True` to MCQ generation.
   - Log: `Global RAG enabled (chunks=N); outline X.XXs`.
3. **Else**: `use_rag=False`, `global_outline=None`. Log: `Global RAG skipped (disabled)` or `Global RAG skipped (chunks=N <= threshold 9)`.

Fallback: if outline/summarization fails or retrieval returns empty, run without RAG (local chunk(s) only).

## What runs when global RAG is enabled

1. **Outline**: Summarize up to `rag_outline_max_chunks` chunks → LLM builds one global outline.
2. **RAG**: FAISS index over all chunks; per batch, retrieve **top_k=5** similar chunks (optional L2 filter via `rag_relevance_max_l2`).
3. **Prompt**: `Document outline:\n{outline}\n\n` + retrieved/local chunks sent to Sonnet (unchanged parallel pipeline).

## Config (env)

| Env / config | Default | Description |
|--------------|---------|-------------|
| USE_GLOBAL_RAG | false | Set true to allow global RAG when doc has enough chunks. |
| RAG_MIN_CHUNKS_FOR_GLOBAL | 9 | Enable outline + RAG only when chunk count **>** this (10+ chunks with default). |
| rag_top_k | 5 | Number of chunks retrieved per batch when use_rag=True. |
| rag_relevance_max_l2 | (none) | Optional. Keep only chunks with L2 ≤ this (~0.9 ≈ cosine > 0.6). |
| rag_outline_max_chunks | 10 | Max chunks summarized for outline (caps latency). |

**Force on:** Set `USE_GLOBAL_RAG=true` and ensure doc is long enough to produce >9 chunks (or lower `RAG_MIN_CHUNKS_FOR_GLOBAL`, e.g. 0, to enable for any chunk count).  
**Force off:** Set `USE_GLOBAL_RAG=false`; all jobs use chunk-only, no outline.

## Affected files

- **app/config.py** – `use_global_rag` (default false), `rag_min_chunks_for_global`, `rag_relevance_max_l2`, `rag_outline_max_chunks`
- **app/jobs/tasks.py** – `run_generation`: chunk once; if `use_global_rag` and `len(chunks) > rag_min_chunks_for_global` → summarize → outline → `use_rag=True`; else skip and log; fallback on outline/retrieval failure
- **app/services/mcq_generation_service.py** – `retrieve_top_k`: optional `max_l2_distance`; fallback when retrieved empty; index build timing log

## Latency impact

| Scenario | Behavior | Added latency |
|----------|----------|----------------|
| Small doc (≤9 chunks) or USE_GLOBAL_RAG=false | Chunk-only, no outline | 0 |
| Large doc (10+ chunks) + USE_GLOBAL_RAG=true | Outline + RAG | ~20–45 s (outline ~15–40 s + FAISS ~0.5–2 s) + ~11 extra LLM calls |

Token cost when enabled: outline adds ~11 summarization calls; roughly +5k–15k input tokens per run.

## Test commands (check logs)

**Short PDF (expect skip):** Upload a 1–2 page PDF, generate N=3. In API logs you should see:
```text
run_generation: Global RAG skipped (chunks=N <= threshold 9)
```
or `Global RAG skipped (disabled)` if `USE_GLOBAL_RAG` is false.

**Long PDF (expect enable when USE_GLOBAL_RAG=true):** Upload a 15+ page PDF, set `USE_GLOBAL_RAG=true` in `.env`, restart, generate N=5. Logs should show:
```text
run_generation: Global RAG enabled (chunks=...); outline X.XXs
run_generation: generate_mcqs_with_rag X.XXs (use_rag=True)
```

**Force RAG on for small docs:** Set `RAG_MIN_CHUNKS_FOR_GLOBAL=0` and `USE_GLOBAL_RAG=true`; any chunk count will use outline + RAG.

## Rollback

- **Disable RAG + outline:** In `.env` set `USE_GLOBAL_RAG=false`. Restart API. All jobs use chunk-only; no outline, no FAISS.
- **Code rollback:** Revert `app/config.py`, `app/jobs/tasks.py`, and the gating block in `run_generation`; optionally revert `app/services/mcq_generation_service.py` if removing the feature entirely.

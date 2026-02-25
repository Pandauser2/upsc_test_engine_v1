# Changelog

## Unreleased

### Added
- **Gemini-only LLM** — MCQ generation and summarization use Google Gemini (`google-generativeai`). Config: `GEN_MODEL_NAME` (default `gemini-1.5-flash-002`), `GEMINI_API_KEY`. See `backend/docs/GEMINI_MIGRATION_STEP1.md`.
- **503 when GEMINI_API_KEY missing** — `POST /tests/generate` returns 503 (detail: set key in backend/.env) instead of enqueueing and returning mock MCQs.
- **Extraction progress** — `Document.total_pages` and `Document.extracted_pages` set during PDF extraction. GET `/documents/{id}` returns them; frontend can show "Extracting pages X/Y". Progress callback in `extract_hybrid`; `run_extraction` updates DB (throttled every 5 pages).
- **API tests for test generation** — `tests/test_tests_api.py`: validation (422 for invalid `num_questions`), 404 for missing document, 202 for valid generate. Skipped when fastapi/httpx not installed.
- **Extraction latency optimization** — Per-page log (`native_text_len`, `ocr_triggered`, `ocr_time`), summary (`native_avg_len`, `ocr_pages_count`, time breakdown). Parallel OCR via `ThreadPoolExecutor(max_workers=12)` for triggered pages only. See `backend/docs/EXTRACTION_LATENCY_OPTIMIZATION.md`.
- **On-demand extraction timeout + metrics** — `GET /documents/{id}/extract` when text empty runs extraction in a thread with timeout (default 600s). On timeout: increment `app.metrics.extraction_timeouts_total`, log warning with `extra` (document_id, timeout_seconds, extraction_timeouts_total), return 200 with `extraction_error`. `pool.shutdown(wait=False)` so request returns immediately. Config: `extract_on_demand_timeout_seconds` (env `EXTRACT_ON_DEMAND_TIMEOUT_SECONDS`).
- **POST /tests/{id}/cancel** — Cancel a pending or generating test (marks failed, "Cancelled by user"). No-op if already completed/partial/failed.
- **409 on duplicate generation** — `POST /tests/generate` returns 409 if a run is already pending/generating for that document.
- **Generation heartbeat** — During `run_generation`, test `updated_at` is refreshed so active jobs aren't cleared as stuck (stale check uses `COALESCE(updated_at, created_at)`).
- **Dynamic stale timeout** — Timeout = `max_stale_generation_seconds` + (num_chunks // 10 * 60) so long PDFs aren't marked `failed_timeout` prematurely.
- **elapsed_time in responses** — Document responses (list, get, GET /documents/{id}/extract) include `elapsed_time` (integer seconds): PDF extraction duration from `run_extraction` (time.monotonic() start→finish), stored in `extraction_elapsed_seconds`; migration 007 adds column. Test responses (list, get, GET /tests/{id}/status) include `elapsed_time`: time from create to done, computed in API as `(updated_at - created_at).total_seconds()` when status is terminal (no DB column).
- **Quality baseline export** — `POST /tests/generate` accepts `export_result: true`. When `ENABLE_EXPORT=true`, completed MCQs are written to `backend/exports/{test_id}.json`. Extra logging (chunks, context length, raw LLM snippet) when enabled. Off by default. See `backend/EXPORT_BASELINE.md`.
- **RAG + global outline (gated)** — When `USE_GLOBAL_RAG=true` (default) and doc has >`RAG_MIN_CHUNKS_FOR_GLOBAL` chunks (default 20 → 21+ chunks), generation builds chunk summaries → global outline → `use_rag=True`. Log `Global RAG activated` with extra `chunks`, `threshold`. FAISS + top_k=5; optional `rag_relevance_max_l2`. Fallback to chunk-only on failure. See `backend/RAG_GLOBAL_OUTLINE.md`.
- **GET /tests/{id}/status** — When status is `pending`/`generating`, message includes "Generating... usually under 1 minute". Progress = `questions_generated / target_questions`; no batch polling.
- **429 retry (Claude)** — `generate_mcqs` retries on rate limit (tenacity, 1–8 s exponential, 4 attempts).
- **Extraction on upload** — PDF upload creates doc with `status=processing` and enqueues `run_extraction`. Background task runs `extract_hybrid` (pdfplumber + optional OCR), sets `extracted_text` and `status=ready` or `extraction_failed`.
- **Text-only generation pipeline** — Generation uses `document.extracted_text` → chunking (semantic/fixed per config) → `generate_mcqs_with_rag` (RAG/outline when `USE_GLOBAL_RAG=true`) → filter bad critique → sort medium first → persist up to N. No vision path in generation.
- **GET /documents/{id}/extract** — Returns extracted text, word/char count, optional page_count and extraction metadata; runs extraction on demand if stored text empty.
- **run_extraction(doc_id, user_id)** — Background task in `app.jobs.tasks`; updates doc `extracted_text` and `status` after PDF extraction.
- **Chunking config** — `chunk_mode` (semantic | fixed), `chunk_size`, `chunk_overlap_fraction` in config; semantic uses spaCy + 20% overlap per EXPLORATION.

### Changed
- **Gemini SDK: google.genai** — Replaced deprecated `google-generativeai` with `google-genai`. All Gemini usage (MCQ generation, validation, summarization, vision pipeline) now uses `from google import genai` and `client.models.generate_content` / `client.chats.create`. Removes FutureWarning. Requirements: `google-genai>=1.0.0` (drop `google-generativeai`).
- **Documentation** — `DOCUMENTATION.md`: Gemini-only backend, `GEN_MODEL_NAME`/`GEMINI_API_KEY`/`OCR_THRESHOLD`, documents progress (`total_pages`/`extracted_pages`), 4 parallel Gemini, link to `EXTRACTION_LATENCY_OPTIMIZATION.md`. `backend/README.md`: env (Gemini, `OCR_THRESHOLD`), extraction progress, Gemini parallelization.
- **LLM: Gemini only** — Claude and OpenAI removed from config and code. `get_llm_service()` returns Gemini or mock. Summarization uses Gemini. Vision pipeline (`vision_mcq.py`) uses Gemini multimodal. Config: `gen_model_name`, `gemini_api_key` only (no `llm_provider`, `claude_*`, `openai_*`).
- **Extraction OCR trigger** — OCR runs only when `len(native_text.strip()) < OCR_THRESHOLD` (default 50, env `OCR_THRESHOLD`). No image_heavy, has_images, or garbled heuristics; fixes OCR on all 100 pages for native-text NCERT PDFs. Table text included in length (pdfplumber tables merged before count).
- **Generation pipeline** — Message Batches removed. All N=1–20 use parallel single Gemini calls (`ThreadPoolExecutor`, max_workers=4). No `batch_id`, no polling; status from DB only. See `backend/GENERATION_REFACTOR_STATUS.md`.
- **run_generation** — Sets `test.questions_generated` after persisting questions. Chunks once; if `use_global_rag` and `len(chunks) > rag_min_chunks_for_global` (default 20), runs summarize → outline → `generate_mcqs_with_rag(..., use_rag=True, global_outline=...)`; logs `Global RAG activated` (extra: chunks, threshold). Else skips RAG and logs. Fallback to no RAG on outline/retrieval failure.
- **Critique filter** — `BAD_CRITIQUE_SUBSTRINGS` narrowed to specific phrases (`incorrect key`, `wrong answer`, `incorrect answer`, `key is wrong`, `explanation is wrong`) so MCQs are not dropped when critique only mentions "incorrect" for distractors.
- **GET /tests/{id}/status** — No longer calls `poll_batch_generations`; reads status and progress from DB only.
- **Auth 401** — "Not authenticated" response now suggests: "Send header: Authorization: Bearer <token>".
- **Global RAG gating** — `USE_GLOBAL_RAG` default true. RAG + outline run only when `len(chunks) > RAG_MIN_CHUNKS_FOR_GLOBAL` (default 20 → 21+ chunks). Limits RAG to longer docs; log "Global RAG activated" or "Global RAG skipped (chunks=N <= threshold 20)". Env override: `RAG_MIN_CHUNKS_FOR_GLOBAL`.
- **Documents API** — PDF upload only. Upload returns 201 with `status=processing`; extraction runs in background. No paste endpoint.
- **Generation requirements** — Requires `doc.status=ready` and non-empty `extracted_text`; enforces `min_extraction_words` (default 500). Generation uses text pipeline only.
- **Startup check** — Validates text pipeline import (`generate_mcqs_with_rag`) instead of vision_mcq.
- **On-demand extraction timeout** — Default `extract_on_demand_timeout_seconds` 120 → 600 (10 min). Env: `EXTRACT_ON_DEMAND_TIMEOUT_SECONDS`.

### Removed
- **Claude/OpenAI from config** — `llm_provider`, `claude_api_key`, `claude_model`, `openai_*` removed from Settings. Legacy env vars ignored via `extra="ignore"`.
- **Message Batches** — `submit_mcq_batch`, `get_batch_status`, `get_batch_results`, `poll_batch_generations`, `_process_one_batch_test`. Batch path and batch_id handling removed from service, tasks, and API.
- **batch_id column** — Migration 006 drops `batch_id` from `generated_tests`. Run `alembic upgrade head` after 005.
- **POST /documents (paste)** — Create document from pasted text removed. PDF upload only.
- **DocumentCreatePaste** — Schema removed from `app.schemas.document`.
- **Vision from generation path** — `run_generation` no longer calls `generate_mcqs_vision`. Vision code remains in repo (`vision_mcq.py`, `pdf_to_images`) but is not used for generation.

### Fixed
- **OCR on all pages for native NCERT PDF** — Trigger was `has_images_list[i]` (true for every page with any image). Now OCR only when native text per page < `OCR_THRESHOLD`; removed image_heavy and has_images from trigger.
- Export dir path when `exports_dir` is set from env as string (normalized to `Path` before use).
- Clear stuck generating: loop variable in `clear_stuck_generating_tests` renamed from `id` to avoid shadowing builtin.
- getattr fallbacks aligned with config: `extract_on_demand_timeout_seconds` 600, `use_global_rag` True in API/tasks.

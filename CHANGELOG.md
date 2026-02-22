# Changelog

## Unreleased

### Added
- **Quality baseline export** — `POST /tests/generate` accepts `export_result: true`. When `ENABLE_EXPORT=true`, completed MCQs are written to `backend/exports/{test_id}.json`. Extra logging (chunks, context length, raw LLM snippet) when enabled. Off by default. See `backend/EXPORT_BASELINE.md`.
- **RAG + global outline (gated)** — Default off. When `USE_GLOBAL_RAG=true` and doc has >`RAG_MIN_CHUNKS_FOR_GLOBAL` chunks (default 9), generation builds chunk summaries → global outline → `use_rag=True`. FAISS + top_k=5; optional `rag_relevance_max_l2`. Fallback to chunk-only on failure. See `backend/RAG_GLOBAL_OUTLINE.md`.
- **GET /tests/{id}/status** — When status is `pending`/`generating`, message includes "Generating... usually under 1 minute". Progress = `questions_generated / target_questions`; no batch polling.
- **429 retry (Claude)** — `generate_mcqs` retries on rate limit (tenacity, 1–8 s exponential, 4 attempts).
- **Extraction on upload** — PDF upload creates doc with `status=processing` and enqueues `run_extraction`. Background task runs `extract_hybrid` (pdfplumber + optional OCR), sets `extracted_text` and `status=ready` or `extraction_failed`.
- **Text-only generation pipeline** — Generation uses `document.extracted_text` → chunking (semantic/fixed per config) → `generate_mcqs_with_rag` (RAG/outline when `USE_GLOBAL_RAG=true`) → filter bad critique → sort medium first → persist up to N. No vision path in generation.
- **GET /documents/{id}/extract** — Returns extracted text, word/char count, optional page_count and extraction metadata; runs extraction on demand if stored text empty.
- **run_extraction(doc_id, user_id)** — Background task in `app.jobs.tasks`; updates doc `extracted_text` and `status` after PDF extraction.
- **Chunking config** — `chunk_mode` (semantic | fixed), `chunk_size`, `chunk_overlap_fraction` in config; semantic uses spaCy + 20% overlap per EXPLORATION.

### Changed
- **Generation pipeline** — Message Batches removed. All N=1–20 use parallel single Claude calls (`ThreadPoolExecutor`, max_workers=4). No `batch_id`, no polling; status from DB only. See `backend/GENERATION_REFACTOR_STATUS.md`.
- **run_generation** — Sets `test.questions_generated` after persisting questions. Chunks once; if `use_global_rag` and `len(chunks) > rag_min_chunks_for_global` (default 9), runs summarize → outline → `generate_mcqs_with_rag(..., use_rag=True, global_outline=...)`; else skips RAG and logs. Fallback to no RAG on outline/retrieval failure.
- **Critique filter** — `BAD_CRITIQUE_SUBSTRINGS` narrowed to specific phrases (`incorrect key`, `wrong answer`, `incorrect answer`, `key is wrong`, `explanation is wrong`) so MCQs are not dropped when critique only mentions "incorrect" for distractors.
- **GET /tests/{id}/status** — No longer calls `poll_batch_generations`; reads status and progress from DB only.
- **Auth 401** — "Not authenticated" response now suggests: "Send header: Authorization: Bearer <token>".
- **Global RAG gating** — `USE_GLOBAL_RAG` default false. RAG + outline run only when `USE_GLOBAL_RAG=true` and `len(chunks) > RAG_MIN_CHUNKS_FOR_GLOBAL` (default 9). Protects small-job latency; log "Global RAG enabled (chunks=N)" or "Global RAG skipped (...)".
- **Documents API** — PDF upload only. Upload returns 201 with `status=processing`; extraction runs in background. No paste endpoint.
- **Generation requirements** — Requires `doc.status=ready` and non-empty `extracted_text`; enforces `min_extraction_words` (default 500). Generation uses text pipeline only.
- **Startup check** — Validates text pipeline import (`generate_mcqs_with_rag`) instead of vision_mcq.

### Removed
- **Message Batches** — `submit_mcq_batch`, `get_batch_status`, `get_batch_results`, `poll_batch_generations`, `_process_one_batch_test`. Batch path and batch_id handling removed from service, tasks, and API.
- **batch_id column** — Migration 006 drops `batch_id` from `generated_tests`. Run `alembic upgrade head` after 005.
- **POST /documents (paste)** — Create document from pasted text removed. PDF upload only.
- **DocumentCreatePaste** — Schema removed from `app.schemas.document`.
- **Vision from generation path** — `run_generation` no longer calls `generate_mcqs_vision`. Vision code remains in repo (`vision_mcq.py`, `pdf_to_images`) but is not used for generation.

### Fixed
- Export dir path when `exports_dir` is set from env as string (normalized to `Path` before use).
- Clear stuck generating: loop variable in `clear_stuck_generating_tests` renamed from `id` to avoid shadowing builtin.

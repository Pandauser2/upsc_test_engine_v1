# Changelog

## Unreleased

### Added
- **Vision-based MCQ generation** — PDF → page images (max 1000px), 3 pages/batch → vision ingest (65s + token throttle) → one-shot MCQ generation → quality-review pass.
- **POST /tests/generate** — Request now requires `num_questions` (1–30) and `difficulty` (EASY | MEDIUM | HARD). Both stored in `generation_metadata`; difficulty is user-only.
- **Options 4 or 5** — Questions support 4 or 5 options; labels A–D or A–E. Stored as JSON array `[{"label":"A","text":"..."}, ...]`. Migration 002 allows `correct_option` E.
- **Strict MCQ validation** — Before DB write: options count 4 or 5, labels sequential, correct_answer in labels. Retry generation once on validation failure; then mark test failed.
- **PDF upload (no extraction)** — Upload sets document `status=ready` immediately; no background text extraction. Generation uses vision pipeline from PDF path.
- **Concurrency limit** — Max 3 concurrent generation jobs (semaphore in `run_generation`).
- **POST /documents/upload** — Multipart PDF upload; file saved; document status `ready` immediately.
- **failure_reason on tests** — GeneratedTest.failure_reason (nullable, 512 chars). Set when status=failed. Returned in GET /tests, GET /tests/{id}. Migration 003; SQLite init auto-adds column if missing.
- **Rate limit protection (ingestion)** — 65s sleep after each batch; rolling 60s token window, sleep 20s if >25k. Throttle only between ingestion batches.
- **Pre-push checks** — backend/scripts/pre_push_checks.py. .gitignore added.

### Removed
- **Paste-from-text document creation** — POST /documents with JSON or form (title, content) removed. Document creation is PDF upload only.
- **POST /documents/{id}/re-extract** — Unused; generation uses vision pipeline from PDF file.
- **GET /documents/{id}/extracted-text** — Unused; no text extraction on upload.
- **Text extraction pipeline** — pdf_extract, chunking, dedupe, ranking, validation; scripts (run_extraction, clear_stuck_generating); demo/test scripts; junk files; PLAN.md, CODE_REVIEW.md, PEER_REVIEW_ACTIONS.md.

### Changed
- **Documents API** — PDF upload only; ready immediately. Generation requires `status=ready` and `file_path`.
- **Image size** — Page images capped at 1000px (re-render with scaled matrix if >1000px). Batches 3 pages (BATCH_MAX_PAGES=3).
- **run_generation** — On exception: logger.exception; set failure_reason=str(e)[:512]; _mark_failed. Clear failure_reason when completed.
- **Export .docx** — Supports options as list `[{label, text}, ...]` or legacy dict.
- **Integration test** — Creates document via POST /documents/upload (test_minimal.pdf) instead of paste; polls doc status until `ready` before starting generation.

### Fixed
- **500 on generate** — SQLite init adds failure_reason column when missing; POST /tests/generate no longer fails on old DBs.
- **Startup crash** — clear_stuck uses raw SQL only so startup works when failure_reason column does not exist.

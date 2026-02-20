# Changelog

## Unreleased

### Added
- **Vision-based MCQ generation** — PDF → 300 DPI page images → batched vision ingest (Claude) → one-shot MCQ generation → quality-review pass. Replaces text extraction + chunk-based generation for PDFs.
- **POST /tests/generate** — Request now requires `num_questions` (1–30) and `difficulty` (EASY | MEDIUM | HARD). Both stored in `generation_metadata`; difficulty is user-only.
- **Options 4 or 5** — Questions support 4 or 5 options; labels A–D or A–E. Stored as JSON array `[{"label":"A","text":"..."}, ...]`. Migration 002 allows `correct_option` E.
- **Strict MCQ validation** — Before DB write: options count 4 or 5, labels sequential, correct_answer in labels. Retry generation once on validation failure; then mark test failed.
- **PDF upload (no extraction)** — Upload sets document `status=ready` immediately; no background text extraction. Generation uses vision pipeline from PDF path.
- **Concurrency limit** — Max 3 concurrent generation jobs (semaphore in `run_generation`).

### Removed
- **Paste-from-text document creation** — POST /documents with JSON or form (title, content) removed. Document creation is PDF upload only.
- **POST /documents/{id}/re-extract** — Unused; generation uses vision pipeline from PDF file.
- **GET /documents/{id}/extracted-text** — Unused; no text extraction on upload.

### Changed
- **Documents API** — PDF upload no longer runs background extraction; document ready immediately for vision generation. (Step 4 remains PDF-only; upload dir resolved relative to backend; stored `file_path` absolute when possible.)
- **Generation (POST /tests/generate)** — For PDFs requires `status=ready` and `file_path`; no extracted_text or min word count. Only PDFs supported. System prompts for Phase 2/3 use full UPSC prompt via `system=`.
- **Export .docx** — Supports options as list `[{label, text}, ...]` or legacy dict.
- **Integration test** — Creates document via POST /documents/upload (test_minimal.pdf) instead of paste; polls doc status until `ready` before starting generation.

### Added
- **POST /documents/upload** — Multipart PDF upload; file saved; document status `ready` immediately.
- **PDF extraction (script/legacy)** — `app/services/pdf_extract` and scripts/run_extraction.py remain for local use; not used by generation.
- **PDF extraction: PyMuPDF first** — `app/services/pdf_extract` tries PyMuPDF, falls back to PyPDF2. Extracts all pages; prefixes each with `[Page N]`.
- **Targeted cleanup in extraction** — Strip `/gid...` refs; remove known city-list header line and standalone page-number lines. Does not remove “repeated lines” globally (to avoid stripping real content).
- **OCR for image-only pages** — Pages with very little or no text layer (< 50 chars) are rendered to an image (PyMuPDF) and run through Tesseract OCR. Requires tesseract installed (e.g. `brew install tesseract` on Mac). If Tesseract is missing, those pages stay empty (no crash).

### Fixed
- **PDF extraction path** — Background task resolves path; fallback to backend-relative path when stored path is relative and file not found. Persist resolved path after successful extraction when stored was relative.
- **Single-page / wrong content** — Extraction iterates all pages; prompt instructs LLM to use entire material and prefer UPSC subject matter over meta-content (revision tips, course ads). Image-only pages now use OCR when Tesseract is installed.

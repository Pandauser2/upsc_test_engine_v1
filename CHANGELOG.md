# Changelog

## Unreleased

### Added
- **Extraction on upload** — PDF upload creates doc with `status=processing` and enqueues `run_extraction`. Background task runs `extract_hybrid` (pdfplumber + optional OCR), sets `extracted_text` and `status=ready` or `extraction_failed`.
- **Text-only generation pipeline** — Generation uses `document.extracted_text` → chunking (semantic/fixed per config) → `generate_mcqs_with_rag(..., use_rag=False)` → filter bad critique → sort medium first → persist up to N. No vision path in generation.
- **GET /documents/{id}/extract** — Returns extracted text, word/char count, optional page_count and extraction metadata; runs extraction on demand if stored text empty.
- **run_extraction(doc_id, user_id)** — Background task in `app.jobs.tasks`; updates doc `extracted_text` and `status` after PDF extraction.
- **Chunking config** — `chunk_mode` (semantic | fixed), `chunk_size`, `chunk_overlap_fraction` in config; semantic uses spaCy + 20% overlap per EXPLORATION.

### Changed
- **Documents API** — PDF upload only. Upload returns 201 with `status=processing`; extraction runs in background. No paste endpoint.
- **Generation requirements** — Requires `doc.status=ready` and non-empty `extracted_text`; enforces `min_extraction_words` (default 500). Generation uses text pipeline only.
- **run_generation** — Reads `extracted_text`, calls `mcq_generation_service.generate_mcqs_with_rag` with `use_rag=False`; filters by BAD_CRITIQUE_SUBSTRINGS; sorts; persists options as dict (LLM text returns `{"A":"...","B":"..."}`).
- **Startup check** — Validates text pipeline import (`generate_mcqs_with_rag`) instead of vision_mcq.

### Removed
- **POST /documents (paste)** — Create document from pasted text removed. PDF upload only.
- **DocumentCreatePaste** — Schema removed from `app.schemas.document`.
- **Vision from generation path** — `run_generation` no longer calls `generate_mcqs_vision`. Vision code remains in repo (`vision_mcq.py`, `pdf_to_images`) but is not used for generation.

### Fixed
- (None this release)

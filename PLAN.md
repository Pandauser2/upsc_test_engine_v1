# Feature Implementation Plan

**Overall Progress:** ~85%

## TLDR

Faculty-facing SaaS that turns UPSC coaching notes (PDF) into Prelims-style MCQs. PDF only; extraction on upload. MVP: user chooses 1–20 questions per test (default 15); PDFs limited to 100 pages. Pipeline (MVP simplified per EXPLORATION §8): generate N or N+5 (cap 20) → self-validation → drop bad critique → simple sort → persist up to N; partial if < N; manual fill up to N.

## Critical Decisions

- **Question count (MVP):** 1–20, user input, default 15; hard reject >20. Pipeline targets N; MVP generates N+5 (cap 20), self-validation drop + simple sort (medium first), no 1.5–2×N or Jaccard dedupe/ranking; partial status + manual fill if < N.
- **PDF page limit (MVP):** Max 100 pages; reject at upload with status `rejected` and user-friendly message; detect pages via PyMuPDF or pdfplumber.
- **Job queue:** FastAPI BackgroundTasks first; add Celery+Redis only if concurrency ≥10 or generation >15s.
- **Chunking:** Semantic (spaCy, 20% overlap) preferred; fixed-size fallback; configurable.
- **Topics:** Fixed list from DB; inject exact slugs into prompt; require verbatim output to avoid FK errors.
- **Deployment:** Docker Compose on single VPS; no K8s for MVP.

## Tasks

- [x] 🟩 **Step 1: Project scaffold and DB** (reused existing)
  - [x] 🟩 Repo structure (backend, .env.example) already present.
  - [x] 🟩 Schema and topic_list seed in place; documents support status `rejected` (string).

- [x] 🟩 **Step 2: Auth** (reused existing)
  - [x] 🟩 JWT (register, login, me) and user-scoped APIs already implemented.

- [x] 🟩 **Step 3: Document upload and page limit**
  - [x] 🟩 POST /documents/upload: detect page count via PyMuPDF; if >100 create doc with status=`rejected`, return 400 with MVP message.
  - [x] 🟩 If ≤100: save file, create document status=`ready` (existing flow).
  - [x] 🟩 PDF upload only; extraction runs in background; doc status processing → ready or extraction_failed.

- [x] 🟩 **Step 4: Test generation API and question count**
  - [x] 🟩 num_questions 1–20, default 15; reject >20 in schema validator. Reject generation for documents with status=rejected.
  - [x] 🟩 202 + BackgroundTasks unchanged.

- [x] 🟩 **Step 5: Generation pipeline** (reused vision pipeline; MVP per EXPLORATION §8)
  - [x] 🟩 Vision pipeline: generate N+5 (cap 20) → self-validation drop (bad critique) → simple sort (medium first) → persist up to N; MAX_QUESTIONS=20; partial if &lt; N; topic slugs injected into prompt; topic_tag parsed and defaulted if unknown.
  - [x] 🟩 Stuck/timeout tests set status=`failed_timeout`.

- [x] 🟩 **Step 6: Tests API** (reused existing)
  - [x] 🟩 List, get, PATCH, POST questions, export already implemented; manual-fill cap set to 20.

- [ ] 🟥 **Step 7: Frontend – upload and generation**
  - [ ] 🟥 Upload form: show "Maximum 100 pages supported in current version"; server enforces.
  - [ ] 🟥 Generation: num_questions 1–20, default 15; show partial/failed_timeout and manual fill.

- [x] 🟩 **Step 8: Config** (reused + extended)
  - [x] 🟩 PROMPT_VERSION, max_generation_time_seconds, LLM keys in .env.example; MAX_PDF_PAGES=100 added.

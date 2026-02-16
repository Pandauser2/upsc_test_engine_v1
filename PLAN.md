# Feature Implementation Plan

**Overall Progress:** `100%`

## TLDR

Faculty-facing web app: upload UPSC coaching notes (PDF or paste text) → generate 50 Prelims-style MCQs with answer, explanation, difficulty, and topic. Faculty can review/edit, add questions manually if generation yields &lt;50 (partial), and export to .docx. Tech: Next.js (App Router, TypeScript), FastAPI (Python 3.11), PostgreSQL, BackgroundTasks (no Redis for MVP), abstracted LLM layer.

**Current scope:** This plan runs through **Step 9** (backend + APIs complete). **Step 10** (frontend minimal slice) and **Step 11** (Docker and runbook) are planned for later.

## Critical Decisions

- **Exactly 50 MCQs per test** — Generate in batches, dedupe (Jaccard/stem), rank (validation heuristic, prefer medium, topic diversity), select best 50; if &lt;50 after max retries → status = partial, notify in-app, allow manual fill.
- **Prompt versioning + cost** — Each test stores prompt_version, model, estimated_input/output_tokens, estimated_cost_usd; max_generation_time_seconds = 300; status partial | failed_timeout when applicable.
- **Topic slug enforcement** — topic_list table; inject exact slugs into prompt, require verbatim output; post-parse default/drop unknown to avoid FK errors.
- **Auth scope** — MVP = faculty only; all documents and tests scoped by user_id; role column (faculty | admin | super_admin) for future scaling.
- **No Redis for MVP** — FastAPI BackgroundTasks; add RQ only if ≥10 concurrent or generation &gt;15s.

## Tasks

- [x] 🟩 **Step 1: Project bootstrap and infra**
  - [x] 🟩 Create repo folder structure (frontend/, backend/, docker-compose, .env.example) per EXPLORATION §2.
  - [x] 🟩 Backend: FastAPI app, config (env), database.py (SQLAlchemy + Postgres), no auth yet.
  - [x] 🟩 Frontend: Next.js App Router + TypeScript, minimal layout and api client base URL.
  - [x] 🟩 docker-compose: Postgres only; backend runnable locally or in container.

- [x] 🟩 **Step 2: Database schema and topic seed**
  - [x] 🟩 Migrations or SQL: users (with role), documents, topic_list, generated_tests, questions per EXPLORATION §3.
  - [x] 🟩 Seed topic_list with initial slugs/names (e.g. polity, economy, history, geography, science, environment).
  - [x] 🟩 SQLAlchemy models: User, Document, TopicList, GeneratedTest, Question.

- [x] 🟩 **Step 3: Auth (faculty-scoped)**
  - [x] 🟩 Register (email + password hash), login (JWT), GET /auth/me with role; default role = faculty.
  - [x] 🟩 All document and test APIs filter by current user id (faculty sees only own).
  - [x] 🟩 Dependency: get current user from Bearer token; 401/403 as needed.

- [x] 🟩 **Step 4: Documents API**
  - [x] 🟩 POST /documents/upload (multipart PDF) → save file, create document row (status uploaded), enqueue BackgroundTasks for extraction.
  - [x] 🟩 POST /documents (title, content) → create document (source_type pasted_text, extracted_text = content, status ready).
  - [x] 🟩 GET /documents, GET /documents/{id} (scoped by user_id); PDF extraction service (text-based only) → update document status and extracted_text.

- [ ] 🟥 **Step 5: Topics API and prompt slug injection**
  - [ ] 🟥 GET /topics → list topic_list (id, slug, name).
  - [ ] 🟥 Prompt helper: load topic slugs from DB/config and inject exact list into MCQ-generation prompt; require “topic_tag must be exactly one of: …” verbatim.

- [ ] 🟥 **Step 6: LLM abstraction and one provider**
  - [ ] 🟥 Define LLM interface: generate_mcqs(chunk, topic_slugs) → List[MCQ], validate_mcq(mcq) → str.
  - [ ] 🟥 One implementation (e.g. OpenAI); config: LLM_PROVIDER, API key, model, PROMPT_VERSION, max_generation_time_seconds = 300.
  - [ ] 🟥 Return structured MCQ with topic_tag as slug; post-parse map unknown slug to default or drop and log.

- [ ] 🟥 **Step 7: Pipeline services (chunk, dedupe, rank, validate)**
  - [ ] 🟥 Chunking: fixed-size split of extracted_text (character or token estimate).
  - [ ] 🟥 Dedupe: Jaccard on stem word sets or n-gram overlap; stem word overlap; same correct_option + overlapping options; keep one per cluster.
  - [ ] 🟥 Rank: validation heuristic (prefer no “incorrect key” in critique); prefer medium difficulty; optional topic diversity when selecting top 50.
  - [ ] 🟥 Validation: call validate_mcq for each selected MCQ; store critique in validation_result.

- [x] 🟩 **Step 8: Generation job (BackgroundTasks)**
  - [x] 🟩 Single background task: given test_id, document_id, user_id, load test (pending → generating), run chunk → generate batches → dedupe → validate → rank → select best 50 (or fewer) → persist questions; set status completed | partial | failed | failed_timeout; enforce 300s timeout.
  - [x] 🟩 Track and persist estimated_input_tokens, estimated_output_tokens, estimated_cost_usd on test.
  - [x] 🟩 If <50 valid after max retries: set status = partial; in-app visibility (no email required for MVP).

- [x] 🟩 **Step 9: Tests API**
  - [x] 🟩 POST /tests/generate (document_id) → create GeneratedTest row (pending), enqueue job, return test_id.
  - [x] 🟩 GET /tests, GET /tests/{id} (with questions); PATCH /tests/{id}; PATCH /tests/{id}/questions/{qid}; POST /tests/{id}/questions (manual fill); all scoped by user_id.
  - [x] 🟩 POST /tests/{id}/export → .docx three sections (questions, answer key, explanations); simple clean format.

---

## Planned for later

- **Step 10: Frontend minimal vertical slice** — Login/register, dashboard, documents (upload/paste/list), tests (list, detail, review/edit, manual add, export), topics dropdown.
- **Step 11: Docker and runbook** — docker-compose (Postgres + backend, optional frontend), README with run instructions and env vars.

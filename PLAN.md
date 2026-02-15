# Feature Implementation Plan

**Overall Progress:** `0%`

## TLDR

Faculty-facing web app: upload UPSC coaching notes (PDF or paste text) → generate 50 Prelims-style MCQs with answer, explanation, difficulty, and topic. Faculty can review/edit, add questions manually if generation yields &lt;50 (partial), and export to .docx. Tech: Next.js (App Router, TypeScript), FastAPI (Python 3.11), PostgreSQL, BackgroundTasks (no Redis for MVP), abstracted LLM layer.

## Critical Decisions

- **Exactly 50 MCQs per test** — Generate in batches, dedupe (Jaccard/stem), rank (validation heuristic, prefer medium, topic diversity), select best 50; if &lt;50 after max retries → status = partial, notify in-app, allow manual fill.
- **Prompt versioning + cost** — Each test stores prompt_version, model, estimated_input/output_tokens, estimated_cost_usd; max_generation_time_seconds = 300; status partial | failed_timeout when applicable.
- **Topic slug enforcement** — topic_list table; inject exact slugs into prompt, require verbatim output; post-parse default/drop unknown to avoid FK errors.
- **Auth scope** — MVP = faculty only; all documents and tests scoped by user_id; role column (faculty | admin | super_admin) for future scaling.
- **No Redis for MVP** — FastAPI BackgroundTasks; add RQ only if ≥10 concurrent or generation &gt;15s.

## Tasks

- [ ] 🟥 **Step 1: Project bootstrap and infra**
  - [ ] 🟥 Create repo folder structure (frontend/, backend/, docker-compose, .env.example) per EXPLORATION §2.
  - [ ] 🟥 Backend: FastAPI app, config (env), database.py (SQLAlchemy + Postgres), no auth yet.
  - [ ] 🟥 Frontend: Next.js App Router + TypeScript, minimal layout and api client base URL.
  - [ ] 🟥 docker-compose: Postgres only; backend runnable locally or in container.

- [ ] 🟥 **Step 2: Database schema and topic seed**
  - [ ] 🟥 Migrations or SQL: users (with role), documents, topic_list, generated_tests, questions per EXPLORATION §3.
  - [ ] 🟥 Seed topic_list with initial slugs/names (e.g. polity, economy, history, geography, science, environment).
  - [ ] 🟥 SQLAlchemy models: User, Document, TopicList, GeneratedTest, Question.

- [ ] 🟥 **Step 3: Auth (faculty-scoped)**
  - [ ] 🟥 Register (email + password hash), login (JWT), GET /auth/me with role; default role = faculty.
  - [ ] 🟥 All document and test APIs filter by current user id (faculty sees only own).
  - [ ] 🟥 Dependency: get current user from Bearer token; 401/403 as needed.

- [ ] 🟥 **Step 4: Documents API**
  - [ ] 🟥 POST /documents/upload (multipart PDF) → save file, create document row (status uploaded), enqueue BackgroundTasks for extraction.
  - [ ] 🟥 POST /documents (title, content) → create document (source_type pasted_text, extracted_text = content, status ready).
  - [ ] 🟥 GET /documents, GET /documents/{id} (scoped by user_id); PDF extraction service (text-based only) → update document status and extracted_text.

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

- [ ] 🟥 **Step 8: Generation job (BackgroundTasks)**
  - [ ] 🟥 Single background task: given document_id and user_id, create GeneratedTest (status generating, prompt_version, model), run extract if needed → chunk → generate batches → dedupe → rank → select best 50 (or fewer) → validate → persist questions; set status completed | partial | failed | failed_timeout; enforce 300s timeout.
  - [ ] 🟥 Track and persist estimated_input_tokens, estimated_output_tokens, estimated_cost_usd on test.
  - [ ] 🟥 If <50 valid after max retries: set status = partial; in-app visibility (no email required for MVP).

- [ ] 🟥 **Step 9: Tests API**
  - [ ] 🟥 POST /tests/generate (document_id) → create GeneratedTest row (pending), enqueue job, return test_id.
  - [ ] 🟥 GET /tests, GET /tests/{id} (with questions); PATCH /tests/{id}; PATCH /tests/{id}/questions/{qid}; POST /tests/{id}/questions (manual fill); all scoped by user_id.
  - [ ] 🟥 POST /tests/{id}/export → .docx three sections (questions, answer key, explanations); simple clean format.

- [ ] 🟥 **Step 10: Frontend minimal vertical slice**
  - [ ] 🟥 Login / register pages; store token; api.ts + auth helpers.
  - [ ] 🟥 Dashboard: list documents (upload PDF + paste text entry points), list tests (status: pending, generating, completed, partial, failed_timeout).
  - [ ] 🟥 Document flow: upload or paste → see list and status; open document detail.
  - [ ] 🟥 Test flow: start generation from document → see test in list with status; open test detail (questions, status partial/completed); full edit per question; manual add question for partial; export .docx.
  - [ ] 🟥 Topics: dropdown for topic_id (from GET /topics) in question edit and manual add.

- [ ] 🟥 **Step 11: Docker and runbook**
  - [ ] 🟥 docker-compose: Postgres + backend (and optionally frontend) for single-VPS run.
  - [ ] 🟥 README: how to run locally and with Docker; env vars (DB, JWT, LLM, max_generation_time_seconds=300).

# upsc-test-engine — Exploration & Architecture

**Status:** Spec locked; ready for implementation planning.  
**Goal:** Faculty-facing SaaS that turns UPSC coaching notes (PDF) into high-quality Prelims-style MCQs with answer, explanation, and difficulty. Generalizable beyond UPSC: question count and topics are configurable.

**Implementation:** Pipeline is **extract → chunk → generate from text**. PDF upload triggers extraction (background); generation uses extracted text, semantic or fixed chunking, LLM per chunk/batch, then aggregate → self-validation drop → simple sort → best N. RAG is optional for a later phase.

---

## 0. Decisions (Locked)

| # | Topic | Decision |
|---|--------|----------|
| 1 | Questions per test (MVP) | **1–20** (user must input; default **15**). Hard guardrail: reject &gt;20 with validation error. Pipeline: target N → generate 1.5–2×N candidates → dedupe/rank → select best N. **MVP implementation (§8):** N+5 (cap 20), self-validation drop, simple sort; no over-generation or dedupe yet. Future phases may allow higher. |
| 2 | Max PDF pages (MVP) | **100** pages per upload. Reject larger PDFs at upload; set document status = **rejected**; return user-friendly error. Detect page count with PyMuPDF or pdfplumber. |
| 3 | Chunking | **Configurable**: **semantic chunking** (spaCy sentences/paragraphs, 20% overlap) preferred; **fixed-size** fallback; **adaptive** for dense PDFs. Generate per chunk and aggregate until target. |
| 4 | Self-validation | **Yes**: LLM self-critique stored in `validation_result` for faculty review. |
| 5 | Input sources | **PDF upload only**. Documents are created via upload; extraction runs (background) and populates `extracted_text`. |
| 6 | Faculty review | **Full edit access**: stem, options, correct answer, explanation, difficulty, topic_id (from topic_list). |
| 7 | Export .docx | **Three sections**: (1) Questions only, (2) Answer key, (3) Explanations. Simple clean format; no fancy UPSC styling. |
| 8 | Job queue | **Start with FastAPI BackgroundTasks** (no Redis). Add RQ only if: ≥10 concurrent jobs **or** generation time > 15 seconds. |
| 9 | Deployment | **Docker Compose on single cloud VPS**. No Kubernetes, no fancy CI/CD for now. |
| 10 | Topic tag | **Fixed list** from `topic_list` table (default); **dynamic topics** allowed (e.g. user-defined tags or free-form when configured). FK enforced for fixed list; optional mapping for dynamic. |
| 11 | Re-run | **Yes**: one document can generate multiple tests (same document → many `GeneratedTest` rows). |
| 12 | Quality guardrail | **Hard guardrail**: Generate 1.5–2×N candidates → rank or dedupe → select **best N** (not first N). Goal: high-quality question set. N = user-provided (1–20 in MVP). **MVP implementation (§8):** N+5, self-validation drop, simple sort; full dedupe/rank deferred. |
| 13 | Prompt versioning | **Critical**: Each generated test stores `prompt_version`, `model`, and generation metadata for reproducibility and debugging. |
| 14 | Cost tracking | **Mission**: Store estimated tokens and cost per test on `generated_tests` for visibility and budgeting. |
| 15 | Hard failure (&lt; N MCQs) | After max retries, if &lt; N valid MCQs: set test status = **partial**, notify faculty, allow **manual fill** (add questions until N). N = user-requested count (1–20 in MVP). |
| 16 | Deduplication | Chunked generation can produce similar stems / same fact reworded; apply **deduplication logic** before ranking (see §5). |
| 17 | Timeout / cancellation | **max_generation_time_seconds = 300** (concrete). If exceeded → status = **failed_timeout**. Large PDFs + retries = long jobs; handle explicitly. |
| 18 | Roles (auth scope) | **MVP**: Simple faculty login; tests and documents scoped to **faculty_id** (user_id). **Model**: Faculty (owner), Admin (e.g. institute), Super-admin (chain level). Multi-user scaling requires strict scope by user/role. |
| 19 | Topic slug in prompt | **Inject exact topic slugs** into MCQ prompt; **require model to output one verbatim**. Otherwise FK errors spike on insert. Post-parse: default or drop unknown slug. |

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLIENT (Browser)                                    │
│                     Next.js App Router + TypeScript                           │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │ HTTP / API calls
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Next.js API Routes (optional BFF)                     │
│              Or direct calls from frontend to FastAPI                         │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend (Python 3.11)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐ │
│  │ Auth        │ │ Documents   │ │ MCQ Gen     │ │ Tests / Review / Export │ │
│  │ (email+pwd) │ │ (upload,    │ │ (chunk →    │ │ (CRUD, .docx)           │ │
│  │             │ │  extract)   │ │  JSON)      │ │                         │ │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └───────────┬─────────────┘ │
│         │               │               │                    │               │
│         └───────────────┴───────────────┼────────────────────┘               │
│                                        │                                     │
│  ┌─────────────────────────────────────▼────────────────────────────────────┐│
│  │              LLM Service (abstracted)                                    ││
│  │  • generate_mcqs(chunk) → List[MCQ]   • validate_mcq(mcq) → critique     ││
│  └─────────────────────────────────────┬────────────────────────────────────┘│
└─────────────────────────────────────────┼─────────────────────────────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
┌─────────────────┐            ┌─────────────────┐            ┌─────────────────┐
│   PostgreSQL    │            │ BackgroundTasks │            │  LLM Provider    │
│   (User,        │            │ or Celery+Redis │            │  (OpenAI /       │
│   Document,     │            │ if conc>5 (§6)  │            │   Anthropic /    │
│   GeneratedTest,│            │  >15s gen time) │            │   local)         │
│   Question,     │            │                 │            │                  │
│   topic_list)   │            │                 │            │                  │
└─────────────────┘            └─────────────────┘            └─────────────────┘
```

**Decisions reflected above:**
- Frontend talks to FastAPI.
- Input: **PDF upload only**. Upload stores the file and enqueues extraction (background); document status goes to **processing** then **ready** (or **extraction_failed**). `extracted_text` is populated by extraction (§4).
- BackgroundTasks (or Celery + Redis when concurrency >5, §6) → **extraction on upload** → for generation: **semantic or fixed chunking** (§0) → **generate from chunks** (LLM per chunk/batch) → aggregate → **rank/dedupe** (MVP: self-validation drop + simple sort) → **select best N** → persist. RAG retrieval optional for later. Prompt version + model + cost stored per test.
- Single abstracted LLM service with optional multi-provider fallback (§6).

---

## 2. Proposed Folder Structure

```
upsc-test-engine/
├── README.md
├── docker-compose.yml              # Postgres + backend (+ Redis when RQ added)
├── .env.example
│
├── frontend/                       # Next.js (App Router, TypeScript)
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx            # Landing / dashboard
│   │   │   ├── login/
│   │   │   ├── register/
│   │   │   ├── documents/          # Upload PDF, list, get one
│   │   │   ├── tests/              # List tests, open one
│   │   │   └── tests/[id]/        # Review/edit screen, export
│   │   ├── components/
│   │   ├── lib/
│   │   │   ├── api.ts              # API client (fetch to FastAPI)
│   │   │   └── auth.ts
│   │   └── types/
│   └── public/
│
├── backend/                        # FastAPI (Python 3.11)
│   ├── pyproject.toml              # or requirements.txt
│   ├── Dockerfile
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py             # SQLAlchemy / async engine, session
│   │   ├── models/                 # DB models
│   │   │   ├── user.py
│   │   │   ├── document.py
│   │   │   ├── generated_test.py
│   │   │   └── question.py
│   │   ├── schemas/                # Pydantic request/response
│   │   ├── api/
│   │   │   ├── auth.py             # register, login, me
│   │   │   ├── documents.py        # upload, list, get one
│   │   │   ├── tests.py            # list tests, get test, update questions
│   │   │   ├── jobs.py             # trigger generation, job status (optional)
│   │   │   └── export.py           # export test to .docx
│   │   ├── services/
│   │   │   ├── auth.py
│   │   │   ├── pdf_extract.py      # PDF → text
│   │   │   ├── chunking.py         # text → chunks (for generation)
│   │   │   ├── mcq_generation.py  # uses LLM service
│   │   │   ├── validation.py      # self-validation pass
│   │   │   └── export_docx.py
│   │   ├── llm/                    # LLM abstraction
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # Abstract interface
│   │   │   └── openai_impl.py      # (or anthropic_impl, etc.)
│   │   ├── prompts/                # Optional: versioned prompt templates (prompt_version in DB)
│   │   └── jobs/                   # BackgroundTasks first; RQ later if needed
│   │       └── tasks.py            # run_extraction, run_generation (chunk → LLM → rank/dedupe → best N → validate)
│   └── tests/
│
└── docs/                           # Optional: API spec, runbooks
    └── api.md
```

---

## 3. DB Schema

**Assumptions:** One document can be used to generate one or more tests. One test has **N questions** (N = user-requested, 1–20 in MVP; or fewer if partial; manual fill allowed up to N). Documents and tests are scoped by **user (faculty)**; role model supports Admin/Super-admin for scaling. **MVP:** Max 100 pages per PDF; uploads exceeding that are rejected (status = **rejected**).

| Entity       | Purpose |
|-------------|---------|
| **User**    | Auth (email + password); **role** (faculty | admin | super_admin); owner of documents and tests (faculty_id = user_id). |
| **Document**| Uploaded file (store path or blob ref, filename, status, link to user). |
| **GeneratedTest** | One test = N MCQs from one document (N = 1–20 in MVP); stores prompt_version, model, token/cost estimates, generation_metadata. |
| **Question** | One MCQ; belongs to one GeneratedTest; topic_id FK to topic_list; optional validation_result. |
| **topic_list** | Fixed list of allowed topics; FK from questions enforces validity. |

**Tables (PostgreSQL):**

```sql
-- Users (role: faculty = default owner; admin/super_admin for future scope)
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(30) NOT NULL DEFAULT 'faculty' CHECK (role IN ('faculty', 'admin', 'super_admin')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Documents (PDF upload only; extraction runs on upload)
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type     VARCHAR(20) NOT NULL DEFAULT 'pdf',  -- pdf only
    filename        VARCHAR(512),
    file_path       VARCHAR(1024),
    file_size_bytes BIGINT,
    title           VARCHAR(512),
    status          VARCHAR(50) NOT NULL DEFAULT 'processing',  -- processing | ready | extraction_failed | rejected (MVP: >100 pages)
    extracted_text  TEXT NOT NULL,            -- full text from PDF extraction (populated by background extraction)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_status ON documents(status);

-- Topic list (fixed; enforced FK from questions)
CREATE TABLE topic_list (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(100) NOT NULL UNIQUE,   -- e.g. 'polity', 'economy'
    name            VARCHAR(255) NOT NULL,          -- e.g. 'Polity', 'Economy'
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Generated tests (one per run; status: partial if < N after max retries; failed_timeout if max_generation_time exceeded)
CREATE TABLE generated_tests (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- faculty_id (owner)
    document_id             UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    title                   VARCHAR(512),             -- optional, e.g. from document name
    status                  VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending | generating | completed | partial | failed | failed_timeout
    prompt_version          VARCHAR(50) NOT NULL,     -- e.g. 'mcq_v1', 'mcq_v2'
    model                   VARCHAR(128) NOT NULL,    -- e.g. 'gpt-4o', 'claude-3-sonnet'
    generation_metadata     JSONB,                    -- optional: temperature, chunk_count, etc.
    estimated_input_tokens  INT,                      -- total input tokens used
    estimated_output_tokens INT,                      -- total output tokens used
    estimated_cost_usd      DECIMAL(12, 6),           -- estimated cost in USD
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Config: max_generation_time_seconds = 300; if job runs longer, set status = failed_timeout

CREATE INDEX idx_generated_tests_user_id ON generated_tests(user_id);
CREATE INDEX idx_generated_tests_document_id ON generated_tests(document_id);

-- Questions (up to target per test; partial test has fewer; manual fill allowed)
CREATE TABLE questions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_test_id   UUID NOT NULL REFERENCES generated_tests(id) ON DELETE CASCADE,
    sort_order          INT NOT NULL,         -- 1..N (gaps allowed for manual insert)
    question            TEXT NOT NULL,
    options             JSONB NOT NULL,       -- {"A":"...", "B":"...", "C":"...", "D":"..."} or E
    correct_option      VARCHAR(1) NOT NULL CHECK (correct_option IN ('A','B','C','D','E')),
    explanation         TEXT NOT NULL,
    difficulty          VARCHAR(20) NOT NULL CHECK (difficulty IN ('easy','medium','hard')),
    topic_id            UUID NOT NULL REFERENCES topic_list(id),  -- enforced fixed list
    validation_result   TEXT,                 -- from self-validation pass (critique)
    source_type         VARCHAR(20),          -- 'text' | 'image' | 'mixed' (extraction origin for this question)
    quality_score       DECIMAL(5, 4),       -- optional 0–1 score from ranking/validation
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (generated_test_id, sort_order)
);

CREATE INDEX idx_questions_generated_test_id ON questions(generated_test_id);
CREATE INDEX idx_questions_topic_id ON questions(topic_id);
```

**Notes:**
- `topic_list`: Seed with initial topics (Polity, Economy, History, Geography, Science, Environment, etc.). **Prompt must inject exact slugs** and require verbatim output; faculty dropdown uses same list.
- `generated_tests.prompt_version`: Identifies which prompt template/version was used (e.g. stored in code or config); enables A/B and reproducibility.
- `generated_tests.generation_metadata`: Optional JSON for chunk_count, batch_count, ranking_params, etc.
- `generated_tests.status`: **partial** = &lt; N questions after max retries (notify faculty, allow manual fill up to N); **failed_timeout** = job exceeded max_generation_time_seconds (300). **documents.status**: **rejected** = upload rejected (MVP: &gt;100 pages).
- `options` as JSONB: flexible for exactly A–D.
- `validation_result`: critique from self-validation pass.
- `questions.source_type`: whether the question was generated from text-extracted content, OCR (image), or mixed.
- `questions.quality_score`: optional 0–1 score from ranking/validation for analytics and filtering.

---

## 4. PDF Extraction Enhancements

**Objective:** Reliably extract content from text-only, image-only, and mixed PDFs so the LLM has full context for conceptual questions.

### Text-only PDFs
- **Libraries:** pdfplumber or PyMuPDF for extraction.
- **Preprocessing:** Normalize text (Unicode normalization, strip control chars), collapse repeated whitespace, remove stray page numbers and headers/footers (regex or heuristics).
- **Output:** Clean full-text per page or document; preserve paragraph boundaries where possible for semantic chunking.

### Image-only PDFs
- **OCR:** Integrate **pytesseract** (Tesseract). Render each page to image (e.g. PyMuPDF `get_pixmap`), run OCR, concatenate text.
- **Async:** Detect low text yield; trigger OCR **asynchronously** (background task or queue) so upload response is fast; poll or webhook for completion.
- **Language:** Configure Tesseract for English (and optional Hindi/regional if needed).

### Mixed PDFs
- **Hybrid:** Extract text/tables with **pdfplumber** (or PyMuPDF) first. For pages or regions with very low text yield, run **pytesseract** on rendered images.
- **Structure preservation:** Merge text and OCR output with structure preserved (e.g. tag image-derived content as `[Image: ...]` or keep page order and section markers for outline generation).

### Detection logic
- **Per-page threshold:** After extraction, check extracted text length per page. If below threshold (e.g. **100 characters**), treat page as image-only and apply OCR for that page.
- **Configurable:** Threshold and OCR on/off configurable via env or document-level setting (e.g. `force_ocr=true` for known scanned docs).

---

## 5. Context Management for Conceptual Questions

**Objective:** Give the LLM enough global and local context so conceptual (cross-chunk) questions are well-grounded.

### Hierarchical processing
- **Per-chunk summaries:** Generate a short summary per chunk (e.g. one LLM call per chunk or sliding window). Store summaries with chunk references.
- **Map-reduce for global context:** Combine chunk summaries into a **global outline or abstract** (single follow-up LLM call or deterministic merge). Use this in the main MCQ prompt so the model “knows” the document’s high-level structure.

### Basic RAG
- **Embeddings:** Use **sentence-transformers** to embed chunks (or sentences). Store embeddings (e.g. in **FAISS** or PostgreSQL with pgvector) keyed by document/chunk.
- **Retrieval:** For each question-generation request (or per batch), **retrieve top-k relevant chunks** by similarity; pass retrieved text + optional global summary to the LLM. Reduces truncation and improves relevance.

### Prompt engineering
- **Document outline:** Extract headings (e.g. from PDF structure or regex on bold/large text); build a short **document outline** and include it in the LLM system or user prompt.
- **Source references:** In prompts, ask the model to **cite source** (e.g. “Section 2.3” or “page 5”); persist in question metadata or explanation for faculty review.

---

## 6. LLM Rate Limit Handling

**Objective:** Avoid 429s and throttling when concurrency or volume grows.

### Queue upgrade (Celery + Redis)
- **When:** Upgrade from FastAPI BackgroundTasks to **Celery + Redis** when concurrency &gt;5 or generation time makes polling/visibility important.
- **Benefits:** Persistent queue, retries, visibility into failed tasks, rate limiting at worker level.

### Batching and backoff
- **Batch LLM calls:** Where possible, send **multiple questions per prompt** (e.g. generate N MCQs in one request) to reduce round-trips and stay under request-based limits.
- **Exponential backoff:** Use **tenacity** (or similar) for retries: exponential backoff with jitter on 429 and 5xx; cap max delay and max retries.

### Multi-provider fallback
- **In llm_service (or equivalent):** Implement **multi-provider fallback**. On repeated 429 (or configurable threshold) from primary (e.g. OpenAI), **switch to Anthropic** (or secondary provider) for the same request or for subsequent requests in the run. Config: primary/secondary provider and API keys; feature flag to enable fallback.

---

## 7. API Contracts (Summary)

Base URL: `http://localhost:8000` (or env `API_BASE_URL`).

### 7.1 Auth

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST   | `/auth/register` | Register (default role: faculty) | `{ "email": string, "password": string }` | `201` + `{ "id": uuid, "email": string }` or token |
| POST   | `/auth/login`     | Login    | `{ "email": string, "password": string }` | `200` + `{ "access_token": string, "token_type": "bearer" }` |
| GET    | `/auth/me`        | Current user | (Bearer token) | `200` + `{ "id": uuid, "email": string, "role": "faculty"|"admin"|"super_admin" }` |

**Auth scope (roles):** See **Role model** below.

**Role model (auth scope):**  
- **Faculty** (default): Own documents and tests only. All list/get/create/update are scoped by `user_id` (faculty_id). MVP = simple faculty login; strict scope so multi-user scaling does not break.  
- **Admin**: Institute-level; can see/manage documents and tests for their scope (e.g. same institute_id). TBD for multi-tenant.  
- **Super-admin**: Chain level; can see/manage across tenants. TBD for multi-tenant.  
For MVP, only **Faculty** is used; every document and generated_test has `user_id` = owning faculty; APIs filter by current user id.

### 7.2 Documents

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST   | `/documents/upload` | Upload PDF (MVP: max 100 pages) | `multipart/form-data`: `file` | `201` + doc (status = **processing**; extraction runs in background). If &gt;100 pages: `4xx`, status = **rejected**. When extraction completes: status = **ready** or **extraction_failed**. |
| GET    | `/documents`        | List my documents | (query: `?limit=20&offset=0`) | `200` + `{ "items": [...], "total": number }` |
| GET    | `/documents/{id}`   | Get one document | — | `200` + document (include `extracted_text` when ready) |

### 7.3 Tests (Generated Tests)

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST   | `/tests/generate`  | Start MCQ generation from document | `{ "document_id": uuid, "num_questions": number, "difficulty": "EASY"\|"MEDIUM"\|"HARD" }` (MVP: **num_questions** must be set and in **1–20**; default 15 if omitted). Server validates; if not in 1–20 → **400** "target_questions must be between 1 and 20". | `202` + `{ "id": uuid, "status": "pending", ... }` |

**Generation start validation:** The server ensures `num_questions` (stored as `target_questions` on the test) is present and within 1–20. Invalid values return **400** with a clear message. No new heavy dependencies; extraction uses existing PyMuPDF/pdfplumber.
| GET    | `/tests`           | List my tests | `?limit=20&offset=0` | `200` + `{ "items": [...], "total": number }` |
| GET    | `/tests/{id}`      | Get test with questions | — | `200` + test + `questions: Question[]` (test.status may be partial, failed_timeout, etc.) |
| PATCH  | `/tests/{id}`      | Update test metadata | `{ "title": string }` | `200` |
| PATCH  | `/tests/{id}/questions/{qid}` | Update single question (full edit) | Body: question, options, correct_option, explanation, difficulty, topic_id | `200` |
| POST   | `/tests/{id}/questions` | **Manual fill**: Add question to test (for partial tests until N) | Body: QuestionPayload (no id) | `201` + question |
| POST   | `/tests/{id}/export` | Export to .docx | — | `200` + binary `.docx` (see Export format below) |

### 7.4 Topics (fixed list)

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET    | `/topics` | List all topics (for dropdown, LLM prompt) | `200` + `{ "items": [ { "id": uuid, "slug": string, "name": string } ] }` |

### 7.5 Jobs (optional but recommended)

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET    | `/jobs/{job_id}/status` | Poll job status | `200` + `{ "status": "queued|started|finished|failed|failed_timeout", "result": {...} }` |

**Question payload (MCQ):**

```ts
// Response/request body shape
interface QuestionPayload {
  id?: string;           // only when persisted
  question: string;
  options: { A: string; B: string; C: string; D: string };
  correct_option: "A" | "B" | "C" | "D";
  explanation: string;
  difficulty: "easy" | "medium" | "hard";
  topic_id: string;      // UUID; FK to topic_list (enforced)
  validation_result?: string;
}
```

**Export .docx format (three sections, simple clean layout):**
- **Section 1:** Questions only (numbering, stem, options A–D).
- **Section 2:** Answer key (Q number → correct option).
- **Section 3:** Explanations (Q number → explanation text).  
No fancy UPSC/OMR styling.

---

## 8. LLM Service Abstraction

**Interface (backend):**

- `generate_mcqs(text_chunk: str, style_hint?: str) -> List[MCQ]`  
  - Input: one chunk of extracted text.  
  - Output: list of MCQs in the specified JSON shape (pipeline collects candidates, then dedupes/ranks and selects best N; N = user-provided, 1–20 in MVP).
- `validate_mcq(mcq: MCQ) -> str`  
  - Input: one MCQ.  
  - Output: critique string (e.g. correctness of key, clarity of question); stored in `validation_result`.

**Target-N pipeline (hard guardrail for quality; N = user-provided, 1–20 in MVP):**  
1. **Generate candidates (MVP simplified):** Request **target N or N+5** (cap 20). No over-generation of 1.5–2×N for MVP; advanced dedupe/rank deferred. Enforce **max_generation_time_seconds = 300**; if exceeded, set status = **failed_timeout** and exit.  
2. **MVP: Self-validation drop (no Jaccard dedupe yet):** Run LLM self-validation on each MCQ; **drop** any whose critique contains "incorrect" or "wrong". Persist survivors with `validation_result`. Jaccard dedupe / multi-criteria ranking deferred for later.  
3. **MVP: Simple sort (optional):** Prefer medium difficulty first when ordering. Full ranking (validation-score heuristic, topic diversity) deferred.  
   - **Validation-score heuristic**: Prefer MCQs whose critique does **not** contain an “incorrect key” (or similar) flag; demote or drop those that do.  
   - **Difficulty preference**: Rank medium-difficulty higher when tying.  
   - **Topic diversity**: When selecting top N, favour spread across topics so the test is not dominated by one topic.  
   Uses existing libraries (PyMuPDF/pdfplumber for extraction); add small deps only if truly needed.
4. **Select best N**: Take the top N from the ranked pool. If after max retries there are &lt; N valid MCQs, apply **Hard failure strategy** (below).
5. **Validate and persist**: Run self-validation on the chosen set; store prompt_version, model, token/cost on the test; persist questions with topic_id from `topic_list`.

**Hard failure strategy (&lt; N valid MCQs after max retries):** Set test status = **partial**. Notify faculty (in-app: test list/detail show status `partial`; optional email). Allow **manual fill** via `POST /tests/{id}/questions` until N questions (N = user-requested count, 1–20 in MVP).

**Timeout:** **max_generation_time_seconds = 300** (concrete cap). If job exceeds it, set test status = **failed_timeout** and stop; frontend/job status reflects `failed_timeout`.

**Topic slug enforcement in prompt:**  
- **Inject the exact list of topic slugs** (from `topic_list`) into the MCQ-generation prompt.  
- **Require the model to output one of them verbatim** (e.g. “topic_tag must be exactly one of: polity, economy, history, …”).  
- Otherwise free-form topic strings will cause **FK errors** when persisting; enforcing verbatim slugs keeps inserts valid.
- Post-parse: if model returns an unknown slug, map to a default topic or drop; log for prompt tuning.

**Implementation:**  
- One module per provider (e.g. `openai_impl.py`) implementing a common interface (e.g. `LLMService` protocol or abstract class).  
- Config: `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, model name, max_tokens, `PROMPT_VERSION` (e.g. `mcq_v1`), **max_generation_time_seconds = 300**. When starting a generation run, record prompt_version and model on the test; enforce 300s timeout and set status = failed_timeout if exceeded; accumulate token counts and compute estimated cost before persisting the test.  
- No LLM calls in HTTP handlers; only in services/background tasks.

**LLM best practices (to implement):**
- **Version prompts** in code or config (e.g. `prompts/mcq_v1.txt`); store `prompt_version` on each test.
- **Few-shot examples** in system or user prompt (1–2 example MCQs) to stabilize format and quality.
- **Source references** in questions (e.g. “Based on Section 2.3”) for traceability and faculty review.

---

## 9. Risks & Mitigations

| Risk / Topic | Mitigation |
|--------------|------------|
| **PDF quality** | **Before implementation:** confirm with stakeholders that their PDFs are text-based (not scanned images). For MVP we support text-based PDFs only; if extraction fails, set document `status = failed` and surface to user. **We will add OCR later** for image-based PDFs. |
| **Rate limits / cost** | Limit concurrent BackgroundTasks if needed; backoff on LLM errors; consider cost alerts. |
| **Auth** | JWT (Bearer); define token expiry in config (e.g. 24h). **Role model**: Faculty (default), Admin, Super-admin; MVP = faculty only, tests/documents scoped to user_id. |
| **File storage** | Local disk under Docker volume for VPS. Move to S3 later if needed. |
| **Generation time** | If >15s or ≥10 concurrent jobs, introduce Celery + Redis per §6. |
| **Topic list** | Single source of truth; **inject exact topic slugs into prompt** and require verbatim output to avoid FK errors. Dynamic topics optional. |
| **Chunking** | Prefer semantic chunking (spaCy, 20% overlap); configurable fixed vs semantic; adaptive for dense PDFs (§0 Decision 2). |
| **Large inputs (PDF size / question volume)** | Mitigated by hard limits: **max 100 pages per PDF** (reject at upload, status = rejected, user-friendly message); **max 20 questions per run** (validation error if &gt;20 requested). Frontend: show "Maximum 100 pages supported in current version" on upload form; client-side validation where possible (server enforces). |

---

## 10. Technical Gaps & MVP Priorities

### Technical gaps (to implement)
- **Auth:** **JWT** for API auth; token expiry configurable (e.g. 24h). **Argon2** for password hashing (replace bcrypt if not already Argon2).
- **Logging:** **structlog** (or equivalent) for structured logs (request_id, user_id, document_id, level) to support debugging and observability.

### MVP priorities
- **Phase 1 (MVP):** Focus on **text and mixed PDFs** first. pdfplumber/PyMuPDF + preprocessing; per-page low-text detection and OCR for mixed. Ensure full context (chunking + optional RAG) for conceptual questions.
  - **Phase 1 boundaries (enforced):** (1) **Question count:** User must input desired count; **1–20 inclusive**; default **15**. Reject &gt;20 with validation error. Pipeline: target N → generate 1.5–2×N candidates → dedupe/rank → best N. Partial if &lt; N after max retries; manual fill up to N. (2) **PDF page limit:** **Max 100 pages** per upload. At upload, detect page count (PyMuPDF or pdfplumber); if &gt;100 → reject, document status = **rejected**, return: *"For MVP, PDFs are limited to 100 pages to ensure fast & high-quality generation. Please split larger files or contact support for bigger documents."* Frontend: show "Maximum 100 pages supported in current version" on upload form; client-side validation if possible (server enforces).
- **Phase 1.1 (OCR):** Add **image-only PDF** support: async OCR with pytesseract; document status “processing” until OCR complete.
- **Test suite:** Add tests for **diverse PDFs** (text-only, image-only, mixed, poor quality) to guard extraction and generation quality.

---

## 11. Next Step

Ready for **implementation plan** (minimal vertical slice task list) and then implementation. See **§4 PDF Extraction**, **§5 Context Management**, **§6 Rate Limit Handling**, and **§10 MVP Priorities** for phased rollout.

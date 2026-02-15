# upsc-test-engine — Exploration & Architecture

**Status:** Spec locked; ready for implementation planning.  
**Goal:** Faculty-facing SaaS that turns UPSC coaching notes (PDF/text) into 50 Prelims-style MCQs with answer, explanation, and difficulty.

---

## 0. Decisions (Locked)

| # | Topic | Decision |
|---|--------|----------|
| 1 | Questions per test | **Exactly 50** questions per document (per run). |
| 2 | Chunking | **Fixed-size chunks**; generate MCQs per chunk and **aggregate until we have 50** (then stop). |
| 3 | Self-validation | **Yes**: LLM self-critique stored in `validation_result` for faculty review. |
| 4 | Input sources | **Both**: PDF upload **and** paste text directly. |
| 5 | Faculty review | **Full edit access**: stem, options, correct answer, explanation, difficulty, topic_id (from topic_list). |
| 6 | Export .docx | **Three sections**: (1) Questions only, (2) Answer key, (3) Explanations. Simple clean format; no fancy UPSC styling. |
| 7 | Job queue | **Start with FastAPI BackgroundTasks** (no Redis). Add RQ only if: ≥10 concurrent jobs **or** generation time > 15 seconds. |
| 8 | Deployment | **Docker Compose on single cloud VPS**. No Kubernetes, no fancy CI/CD for now. |
| 9 | Topic tag | **Fixed list** from `topic_list` table; FK enforced. LLM and faculty choose from same list. |
| 10 | Re-run | **Yes**: one document can generate multiple tests (same document → many `GeneratedTest` rows). |
| 11 | 50-MCQ quality | **Hard guardrail**: Generate in batches → rank or dedupe → select **best 50** (not first 50). Goal: high-quality question set. |
| 12 | Prompt versioning | **Critical**: Each generated test stores `prompt_version`, `model`, and generation metadata for reproducibility and debugging. |
| 13 | Cost tracking | **Mission**: Store estimated tokens and cost per test on `generated_tests` for visibility and budgeting. |
| 14 | Hard failure (<50 MCQs) | After max retries, if &lt;50 valid MCQs: set test status = **partial**, notify faculty, allow **manual fill** (add questions until 50). |
| 15 | Deduplication | Chunked generation can produce similar stems / same fact reworded; apply **deduplication logic** before ranking (see §5). |
| 16 | Timeout / cancellation | **max_generation_time_seconds = 300** (concrete). If exceeded → status = **failed_timeout**. Large PDFs + retries = long jobs; handle explicitly. |
| 17 | Roles (auth scope) | **MVP**: Simple faculty login; tests and documents scoped to **faculty_id** (user_id). **Model**: Faculty (owner), Admin (e.g. institute), Super-admin (chain level). Multi-user scaling requires strict scope by user/role. |
| 18 | Topic slug in prompt | **Inject exact topic slugs** into MCQ prompt; **require model to output one verbatim**. Otherwise FK errors spike on insert. Post-parse: default or drop unknown slug. |

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
│   (User,        │            │ (no Redis now;  │            │  (OpenAI /       │
│   Document,     │            │  RQ if 10+      │            │   Anthropic /    │
│   GeneratedTest,│            │  >15s gen time) │            │   local)         │
│   Question,     │            │                 │            │                  │
│   topic_list)   │            │                 │            │                  │
└─────────────────┘            └─────────────────┘            └─────────────────┘
```

**Decisions reflected above:**
- Frontend talks to FastAPI.
- Input: PDF upload **or** paste text; both produce a document with `extracted_text`.
- BackgroundTasks (no Redis) → text extraction (or use pasted text) → fixed-size chunking → **generate in batches** → **rank/dedupe** → **select best 50** → self-validation pass → persist. Prompt version + model + cost stored per test.
- Single abstracted LLM service for generation and self-validation.

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
│   │   │   ├── documents/          # Upload PDF, paste text, list
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
│   │   │   ├── chunking.py         # text → chunks (for 50 MCQs)
│   │   │   ├── mcq_generation.py  # uses LLM service
│   │   │   ├── validation.py      # self-validation pass
│   │   │   └── export_docx.py
│   │   ├── llm/                    # LLM abstraction
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # Abstract interface
│   │   │   └── openai_impl.py      # (or anthropic_impl, etc.)
│   │   ├── prompts/                # Optional: versioned prompt templates (prompt_version in DB)
│   │   └── jobs/                   # BackgroundTasks first; RQ later if needed
│   │       └── tasks.py            # run_extraction_and_generation (batches → rank/dedupe → best 50 → validate)
│   └── tests/
│
└── docs/                           # Optional: API spec, runbooks
    └── api.md
```

---

## 3. DB Schema

**Assumptions:** One document can be used to generate one or more tests. One test has exactly 50 questions (or fewer if partial; manual fill allowed). Documents and tests are scoped by **user (faculty)**; role model supports Admin/Super-admin for scaling.

| Entity       | Purpose |
|-------------|---------|
| **User**    | Auth (email + password); **role** (faculty | admin | super_admin); owner of documents and tests (faculty_id = user_id). |
| **Document**| Uploaded file (store path or blob ref, filename, status, link to user). |
| **GeneratedTest** | One test = 50 MCQs from one document; stores prompt_version, model, token/cost estimates, generation_metadata. |
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

-- Documents (PDF upload OR pasted text)
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type     VARCHAR(20) NOT NULL CHECK (source_type IN ('pdf', 'pasted_text')),
    filename        VARCHAR(512),             -- for PDF; null for pasted text
    file_path       VARCHAR(1024),           -- for PDF; null for pasted text
    file_size_bytes BIGINT,
    title           VARCHAR(512),             -- optional; for pasted text often used as name
    status          VARCHAR(50) NOT NULL DEFAULT 'uploaded',  -- uploaded | processing | ready | failed
    extracted_text  TEXT NOT NULL,            -- full text: from PDF extraction or pasted content
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

-- Generated tests (one per run; status: partial if <50 after max retries; failed_timeout if max_generation_time exceeded)
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

-- Questions (up to 50 per test; partial test has <50; manual fill can add until 50)
CREATE TABLE questions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    generated_test_id   UUID NOT NULL REFERENCES generated_tests(id) ON DELETE CASCADE,
    sort_order          INT NOT NULL,         -- 1..50 (gaps allowed for manual insert)
    question            TEXT NOT NULL,
    options             JSONB NOT NULL,       -- {"A":"...", "B":"...", "C":"...", "D":"..."}
    correct_option      VARCHAR(1) NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    explanation         TEXT NOT NULL,
    difficulty          VARCHAR(20) NOT NULL CHECK (difficulty IN ('easy','medium','hard')),
    topic_id            UUID NOT NULL REFERENCES topic_list(id),  -- enforced fixed list
    validation_result   TEXT,                 -- from self-validation pass (critique)
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
- `generated_tests.status`: **partial** = &lt;50 questions after max retries (notify faculty, allow manual fill); **failed_timeout** = job exceeded max_generation_time_seconds (300).
- `options` as JSONB: flexible for exactly A–D.
- `validation_result`: critique from self-validation pass.

---

## 4. API Contracts (Summary)

Base URL: `http://localhost:8000` (or env `API_BASE_URL`).

### 4.1 Auth

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

### 4.2 Documents

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST   | `/documents/upload` | Upload PDF | `multipart/form-data`: `file` | `202` + `{ "id": uuid, "filename": string, "status": "uploaded" }` (BackgroundTasks) |
| POST   | `/documents`        | Create from pasted text | `{ "title": string, "content": string }` | `201` + `{ "id": uuid, "title": string, "status": "ready" }` (no job; `extracted_text` = content) |
| GET    | `/documents`        | List my documents | (query: `?limit=20&offset=0`) | `200` + `{ "items": [...], "total": number }` |
| GET    | `/documents/{id}`   | Get one document | — | `200` + document (include `extracted_text` or snippet by design) |

### 4.3 Tests (Generated Tests)

| Method | Path | Description | Request | Response |
|--------|------|-------------|---------|----------|
| POST   | `/tests/generate`  | Start MCQ generation from document | `{ "document_id": uuid }` | `202` + `{ "test_id": uuid, "status": "pending" }` |
| GET    | `/tests`           | List my tests | `?limit=20&offset=0` | `200` + `{ "items": [...], "total": number }` |
| GET    | `/tests/{id}`      | Get test with questions | — | `200` + test + `questions: Question[]` (test.status may be partial, failed_timeout, etc.) |
| PATCH  | `/tests/{id}`      | Update test metadata | `{ "title": string }` | `200` |
| PATCH  | `/tests/{id}/questions/{qid}` | Update single question (full edit) | Body: question, options, correct_option, explanation, difficulty, topic_id | `200` |
| POST   | `/tests/{id}/questions` | **Manual fill**: Add question to test (for partial tests until 50) | Body: QuestionPayload (no id) | `201` + question |
| POST   | `/tests/{id}/export` | Export to .docx | — | `200` + binary `.docx` (see Export format below) |

### 4.4 Topics (fixed list)

| Method | Path | Description | Response |
|--------|------|-------------|----------|
| GET    | `/topics` | List all topics (for dropdown, LLM prompt) | `200` + `{ "items": [ { "id": uuid, "slug": string, "name": string } ] }` |

### 4.5 Jobs (optional but recommended)

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

## 5. LLM Service Abstraction

**Interface (backend):**

- `generate_mcqs(text_chunk: str, style_hint?: str) -> List[MCQ]`  
  - Input: one chunk of extracted text.  
  - Output: list of MCQs in the specified JSON shape (fewer or more than 50 per chunk is fine; pipeline can combine/slice to 50).
- `validate_mcq(mcq: MCQ) -> str`  
  - Input: one MCQ.  
  - Output: critique string (e.g. correctness of key, clarity of question); stored in `validation_result`.

**50-MCQ pipeline (hard guardrail for quality):**  
1. **Generate in batches**: Split `extracted_text` into fixed-size chunks; for each chunk call `generate_mcqs(chunk)` and collect all candidate MCQs (typically more than 50). Enforce **max_generation_time_seconds = 300**; if exceeded, set status = **failed_timeout** and exit.  
2. **Deduplicate (MVP: simple methods):** Chunked generation can produce similar stems and same fact reworded. Use **Jaccard similarity** on stem word sets (or n-gram overlap) and/or **stem word overlap** checks (e.g. significant shared tokens); same correct answer + overlapping options can also flag duplicates. Keep one representative per cluster, drop near-duplicates. No embeddings for MVP.  
3. **Rank (MVP criteria explicit):**  
   - **Validation-score heuristic**: Prefer MCQs whose critique does **not** contain an “incorrect key” (or similar) flag; demote or drop those that do.  
   - **Prefer medium difficulty**: Rank medium-difficulty questions higher when tying; optional weight.  
   - **Topic diversity (optional)**: When selecting top 50, favour spread across topics so the test is not dominated by one topic.  
4. **Select best 50**: Take the top 50 from the ranked pool. If after max retries there are <50 valid MCQs, apply **Hard failure strategy** (below).  
5. **Validate and persist**: Run self-validation on the chosen set; store prompt_version, model, token/cost on the test; persist questions with topic_id from `topic_list`.

**Hard failure strategy (<50 valid MCQs after max retries):** Set test status = **partial**. Notify faculty (in-app: test list/detail show status `partial`; optional email). Allow **manual fill** via `POST /tests/{id}/questions` until 50 questions.

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

---

## 6. Risks & Mitigations

| Risk / Topic | Mitigation |
|--------------|------------|
| **PDF quality** | **Before implementation:** confirm with stakeholders that their PDFs are text-based (not scanned images). For MVP we support text-based PDFs only; if extraction fails, set document `status = failed` and surface to user. **We will add OCR later** for image-based PDFs. |
| **Rate limits / cost** | Limit concurrent BackgroundTasks if needed; backoff on LLM errors; consider cost alerts. |
| **Auth** | JWT (Bearer); define token expiry in config (e.g. 24h). **Role model**: Faculty (default), Admin, Super-admin; MVP = faculty only, tests/documents scoped to user_id. |
| **File storage** | Local disk under Docker volume for VPS; same for pasted text (no file). Move to S3 later if needed. |
| **Generation time** | If >15s or ≥10 concurrent jobs, introduce RQ + Redis per decision #7. |
| **Topic list** | Single source of truth; **inject exact topic slugs into prompt** and require verbatim output to avoid FK errors. |

---

## 7. Next Step

Ready for **implementation plan** (minimal vertical slice task list) and then implementation.

# Step 1: Migrate MCQ generation from Claude Sonnet to Gemini Flash

Functional baseline with Gemini as sole model for latency and quality measurement. Parallel structure unchanged (4 candidates via ThreadPoolExecutor).

**Note:** This doc describes the original migration. The codebase now uses the **google.genai** SDK (package `google-genai`), not `google-generativeai`. See `app/llm/gemini_impl.py` and `requirements.txt` for the current implementation.

---

## Summary of changes

- **New:** `app/llm/gemini_impl.py` — `GeminiService` with `generate_mcqs` and `validate_mcq`, JSON output, safety settings, tenacity retries (429/500).
- **Config:** `gen_model_name` (default `claude-sonnet-4-20250514`), `gemini_api_key`. When `gen_model_name` starts with `gemini`, `get_llm_service()` returns Gemini.
- **LLM selection:** `app/llm/__init__.py` — if `gen_model_name.lower().startswith("gemini")` → Gemini, else Claude/OpenAI.
- **Service:** `generate_mcqs_with_rag` unchanged (still calls `get_llm_service()`); added log "Using LLM: {active_llm_model}".
- **Startup:** `main.py` logs "Using LLM: {gen_model_name}" and Gemini key status when model is Gemini.

---

## Projected latency reduction (N=10, 100-page PDF)

| Phase | Claude Sonnet (est.) | Gemini Flash (est.) |
|-------|----------------------|----------------------|
| Parallel generate_mcqs (4 calls, wall) | 25–45 s | **8–18 s** |
| Validation loop (12–15 MCQs) | 36–120 s | **15–40 s** |
| Chunking + FAISS + outline | ~20–55 s | ~20–55 s (unchanged) |
| **Total** | **~85–230 s** | **~45–115 s** |

Gemini Flash is typically 2–3× faster per token and lower latency per request than Sonnet. Expect **~40–50% lower end-to-end** for the same pipeline; validation remains sequential so its share of time stays high.

---

## Affected files and functions

| File | Change |
|------|--------|
| **app/config.py** | Added `gen_model_name`, `gemini_api_key`. `active_llm_model` returns `gen_model_name` when set. |
| **app/llm/gemini_impl.py** | **New.** `get_llm_service()`, `GeminiService`, `generate_mcqs`, `validate_mcq`, `_parse_mcqs_json` (accepts `answer` or `correct_option`), tenacity, safety_settings. |
| **app/llm/__init__.py** | `get_llm_service()`: if `gen_model_name.startswith("gemini")` → `gemini_impl.get_llm_service()`, else Claude/OpenAI. |
| **app/services/mcq_generation_service.py** | One log line: "Using LLM: {active_llm_model}" after `get_llm_service()`. No change to 4 candidates or flow. |
| **app/jobs/tasks.py** | No code change (uses `get_llm_service()` via mcq_generation_service; test model from `settings.active_llm_model`). |
| **app/main.py** | Startup: log "Using LLM: {gen_model_name}"; if Gemini, log Gemini API key status. |
| **requirements.txt** | Added `google-generativeai>=0.8.0`. |

---

## Minimal code diffs (key parts)

### gemini_impl.py (new file)

- `GeminiService.__init__`: `genai.configure(api_key)`, `GenerativeModel(model_name, system_instruction=MCQ_GEN_SYSTEM, safety_settings=...)`.
- `generate_mcqs`: same prompt shape as Claude; `generation_config` with `response_mime_type="application/json"`; tenacity retry; `_parse_mcqs_json` normalizes `answer` → `correct_option`.
- `validate_mcq`: separate `GenerativeModel` for critique; same safety_settings.
- Token counts from `response.usage_metadata.prompt_token_count` / `candidates_token_count` (or `output_token_count`).

### mcq_generation_service.py

```python
llm = get_llm_service()
logger.info("generate_mcqs_with_rag: Using LLM: %s", getattr(settings, "active_llm_model", ...))
```

### __init__.py

```python
gen_model = (getattr(settings, "gen_model_name", None) or "").strip()
if gen_model.lower().startswith("gemini"):
    return _get_gemini()  # with fallback to Claude on exception
# else existing Claude/OpenAI
```

---

## Manual steps

1. **Install dependency**
   ```bash
   pip install google-generativeai
   ```
   (Or from repo: `cd backend && pip install -r requirements.txt`.)

2. **Environment**
   - Set `GEMINI_API_KEY` in `backend/.env` or in the shell.
   - Set `GEN_MODEL_NAME=gemini-1.5-flash-002` (or `gemini-2.0-flash` etc.) to use Gemini. Omit or set to a non-gemini name to keep Claude.

3. **Verify**
   - Start backend; logs should show "Using LLM: gemini-1.5-flash-002" and "Gemini: API key loaded".
   - Run a test generation (e.g. POST /tests/generate with a ready document); poll GET /tests/{id}/status; confirm completion and question count.

---

## Suggested unit tests

1. **Parse Gemini JSON (mock response → MCQs)**
   - In `tests/test_gemini_impl.py` (or equivalent): call `_parse_mcqs_json` with a string that has `{"mcqs": [{"question": "...", "options": {"A":"...","B":"..."}, "correct_option": "A", "explanation": "...", "difficulty": "medium", "topic_tag": "polity"}]}`.
   - Assert list length, keys `question`, `options`, `correct_option`, `explanation`, `difficulty`, `topic_tag`.
   - Test variant with `"answer"` instead of `"correct_option"` and assert it normalizes to `correct_option`.

2. **Mock Gemini generate_mcqs**
   - Patch `google.generativeai.GenerativeModel` or `genai.configure`; return a fake response with `.text = '{"mcqs": [...]}'` and `.usage_metadata` with token counts.
   - Instantiate `GeminiService`, call `generate_mcqs(text, topic_slugs=["polity"], num_questions=2)`.
   - Assert returned list length, structure, and token counts.

3. **LLM selection**
   - With `settings.gen_model_name = "gemini-1.5-flash"`, assert `get_llm_service()` returns an instance that has `generate_mcqs` (e.g. GeminiService).
   - With `gen_model_name = "claude-sonnet-4-20250514"`, assert Claude (or mock) is returned.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| **Parsing differences** | Same JSON shape as Claude; `_parse_mcqs_json` accepts `answer` or `correct_option`. Strip markdown fences. |
| **Quality regression (UPSC nuance)** | Compare side-by-side: same document, Claude vs Gemini; measure pass rate / expert score. A/B or shadow mode. |
| **Rate limits (429)** | Tenacity: 3 attempts, exponential backoff 1–8 s. If persistent, reduce concurrency or add client-side throttling. |
| **Gemini safety block** | Safety_settings set to BLOCK_NONE for all categories so educational content is not blocked. |

---

## Single-phase execution plan

1. **Implement** — Add config, `gemini_impl.py`, `__init__.py` selection, logging in service and main, requirements.
2. **Install** — `pip install google-generativeai`.
3. **Configure** — Set `GEMINI_API_KEY` and `GEN_MODEL_NAME=gemini-1.5-flash-002`.
4. **Smoke test** — Start app, trigger one generation, confirm "Using LLM: gemini-1.5-flash-002" and test completion.
5. **Measure** — Run N=10 on 100-page PDF; collect latency (existing perf_counter logs) and spot-check quality.
6. **Optional** — Add unit tests for `_parse_mcqs_json` and mock `generate_mcqs`.

No DB migration; no change to `tasks.run_generation` logic. Optional second phase: add A/B (store `gen_model_name` or provider per test) and quality comparison.

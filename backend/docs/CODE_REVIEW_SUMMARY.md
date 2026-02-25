# Code Review Summary (LLM / Gemini / OCR / Key loading)

## ✅ Looks Good

- **Logging:** Uses `logger` (e.g. `logger.info`, `logger.warning`, `logger.exception`) throughout; no `console.log` or stray `print()` in production paths. Debug logging in pdf_extraction is behind `logger.debug` and env `PDF_EXTRACT_DEBUG_SAVE`.
- **Error handling:** Try/except in async/sync paths; tenacity retries for Gemini (429/5xx); job marks test failed with clear message when key missing; API returns 503 with actionable detail when key not set.
- **Production readiness:** No hardcoded API keys; secrets from env/`.env`. No TODOs left in critical paths. `DEBUG_SAMPLE_LEN` / debug logs are appropriate for diagnostics.
- **Security:** Auth required on document/test endpoints; `get_current_user` dependency; key never logged (only length). Input validation (num_questions 1–20, document_id UUID, etc.).
- **Architecture:** Single source for Gemini key (`get_gemini_api_key()` in gemini_impl); API, job, main, summarization, vision all use it. OCR trigger is a single condition in one place (pdf_extraction_service).
- **OCR threshold:** Text-heavy pages skip OCR: `force_ocr = final_native_len < ocr_threshold`; table text included in `page_text` before length check; comment in code and EXTRACTION_LATENCY_OPTIMIZATION.md.
- **Mock vs real:** Mock used only when key is missing or `ImportError` (SDK not installed); all other exceptions re-raised so tests don’t silently get mock when Gemini fails.

## ⚠️ Issues Found and Fixed

- **[LOW]** **api/tests.py** — Duplicate `get_gemini_api_key()` call in generate endpoint.
  - **Fix:** Call once and store in `gemini_key`; use it in the 503 check.
- **[LOW]** **Test coverage** — No test asserting that with key set we use Gemini (not mock).
  - **Fix:** Added `test_get_llm_service_returns_gemini_when_key_set` in test_gemini_impl.py (skips if `google.genai` not installed; when run with SDK, asserts `get_llm_service()` returns `GeminiService`).

## 📊 Summary

- **Files reviewed:** app/llm (__init__, gemini_impl, mock_impl), app/api/tests, app/jobs/tasks, app/services/summarization_service, app/llm/vision_mcq, app/config, app/main, app/services/pdf_extraction_service.
- **Critical issues:** 0.
- **Warnings:** 0.
- **Low / improvements:** 2 (duplicate key call, test for Gemini-not-mock).

## Latency and real questions

- **Key loading:** One resolver `get_gemini_api_key()` (settings → env → load `backend/.env`); used everywhere so background job and API see the key. No mock once key is set and SDK is available.
- **OCR:** Only runs when `final_native_len < ocr_threshold` (default 50); text-heavy pages are skipped, so latency stays low for native-text PDFs.
- **Generation:** 4 parallel Gemini calls (ThreadPoolExecutor); tenacity retries on 429/5xx. Real questions when `GEMINI_API_KEY` is set in `.env` and `google-genai` is installed; mock only when key is missing or SDK unavailable.
- **Tests:** 18 passed, 12 skipped (optional deps / FastAPI). New test ensures that with key set and SDK present, `get_llm_service()` returns `GeminiService` (so no silent fallback to mock).

## How to confirm real questions locally

1. Set `GEMINI_API_KEY` in `backend/.env`.
2. Install: `pip install google-genai`.
3. Start backend: `uvicorn app.main:app --reload --port 8000`.
4. Check startup log: “Gemini: API key loaded (len=…)”.
5. Create a test via `POST /tests/generate`; poll `GET /tests/{id}/status` until completed; `GET /tests/{id}`.
6. Verify response: `questions[].question` should not contain the string `"[Mock]"`; explanations should be content-specific, not “Mock explanation…”.

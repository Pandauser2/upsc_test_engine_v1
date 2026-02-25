# Document Extraction Latency: Analysis & Optimization

## Goal
Reduce extraction time for 100-page PDF from **~283 s** to **<60–90 s** while preserving text accuracy for UPSC MCQ generation.

---

## Current Breakdown (Estimate for 100-Page PDF)

| Phase | Estimate | Notes |
|-------|----------|--------|
| Native extraction (PyMuPDF + pdfplumber) | ~5–15 s | One open per doc; per-page blocks + pdfplumber fill for empty pages |
| Preprocessing (mojibake, preprocess, tables) | ~5–15 s | Per-page sequential; ftfy + tables |
| **OCR (sequential, per page)** | **~200–260 s** | **Main bottleneck**: 2–3 s per page × many pages (image-heavy or low-text threshold) |
| Final clean | ~2–5 s | Dedupe, merge lines, normalize |
| **Total** | **~283 s** | |

OCR dominates because it runs sequentially; each page render + Tesseract + preprocessing is ~2–3 s.

---

## Optimizations Implemented (Phase 1)

### 1. Instrumentation (perf_counter logs)
- **Total extraction** time logged at end.
- **Native extraction** time: first block (PyMuPDF blocks + pdfplumber fill).
- **Preprocessing** time: per-page mojibake + preprocess + tables (sequential).
- **OCR**: trigger count, total OCR time (parallel block), workers count.
- **Final clean** time.

### 1b. Per-page and summary logs
- **Per-page** (each page): `native_text_len`, `ocr_triggered` (bool), `ocr_time` (seconds for that page).
- **Summary**: `ocr_pages_count`, `native_avg_len` (average native chars per page), plus total/preprocess/ocr/final_clean times.

Example log output:
```
extract_hybrid: native_extraction pages=100 total_native_chars=... time=12.34s
extract_hybrid: preprocessing_time=8.50s ocr_trigger_count=5 (of 100 pages) ocr_threshold=50
extract_hybrid page 1: native_text_len=1204 ocr_triggered=False ocr_time=0.00s
extract_hybrid page 2: native_text_len=980 ocr_triggered=False ocr_time=0.00s
...
extract_hybrid: ocr_pages=5 ocr_total_time=12.00s (parallel workers=5)
extract_hybrid summary: total=38.00s (native=12.34s preprocess=8.50s ocr=12.00s final_clean=1.20s) pages=100 ocr_pages_count=5 native_avg_len=950.2 cleaned_length=...
```

### 2. OCR trigger (strict: image-dominated pages only)
- **OCR only when** page is image-dominated: `len(native_text.strip()) < OCR_THRESHOLD` (default **50**; env `OCR_THRESHOLD`; use 100 for "less than 100 character" rule).
- **Single condition**: `force_ocr = final_native_len < ocr_threshold`. No image_heavy, no has_images, no garbled heuristics—so native-text NCERT PDFs never trigger OCR.
- Config: `app/config.py` `ocr_threshold: int = 50`. Set `OCR_THRESHOLD=100` in env for a 100-character cutoff.
- Native text length is computed **after** mojibake fix, preprocess, and **table extraction** (pdfplumber), so table text is included and is not missed by the threshold.

### 3. Parallel OCR
- Pages that need OCR are run in **ThreadPoolExecutor(max_workers=12)**.
- Each worker calls `_ocr_page_pymupdf(path, page_index, ...)` (opens PDF in worker; avoids PyMuPDF thread-safety issues).
- Logs: `ocr_pages=N ocr_total_time=Xs (parallel workers=12)`.

### 4. Progress callback
- `extract_hybrid(..., progress_callback=fn)` with `fn(extracted_pages: int, total_pages: int)`.
- **DB**: `documents.total_pages`, `documents.extracted_pages` (set at start; throttled updates every 5 pages).
- **API**: GET `/documents/{id}` returns `status`, `total_pages`, `extracted_pages` → use as **document status** ("Extracting pages X/Y" when `status == "processing"`).

### 5. Cache
- **Extracted text** is stored in **Document.extracted_text** (and returned by GET `/documents/{id}` and GET `/documents/{id}/extract`). No separate file path cache in this phase.

---

## Affected Files & Functions

| File | Change |
|------|--------|
| `app/config.py` | `ocr_threshold: int = 50` (env `OCR_THRESHOLD`) |
| `app/services/pdf_extraction_service.py` | `extract_hybrid`: use `ocr_threshold` for trigger; `_ocr_page_with_timing` for per-page OCR time; per-page log `native_text_len`, `ocr_triggered`, `ocr_time`; summary `ocr_pages_count`, `native_avg_len`; Phase 3 parallel OCR unchanged (ThreadPoolExecutor max_workers=12) |
| `app/jobs/tasks.py` | `run_extraction`: get page count (pymupdf), set `total_pages`/`extracted_pages`; pass `_progress` to `extract_hybrid`; set `extracted_pages=result.page_count` on completion |
| `app/models/document.py` | Added `total_pages: int \| None`, `extracted_pages: int = 0` |
| `app/schemas/document.py` | `DocumentResponse`: added `total_pages`, `extracted_pages` |
| `app/api/documents.py` | `_doc_to_response`: include `total_pages`, `extracted_pages` |
| `app/database.py` | SQLite init: add columns `total_pages`, `extracted_pages` if missing |

---

## Test Commands

### 1. Run extraction on a 100-page PDF (backend dir)
```bash
cd backend
# Ensure .env has DB path, etc.
python -c "
from pathlib import Path
from app.services.pdf_extraction_service import extract_hybrid
path = Path('path/to/your_100page.pdf')  # set real path
result = extract_hybrid(path)
print('page_count', result.page_count)
print('ocr_used_pages', len(result.used_ocr_pages))
print('text_len', len(result.text))
print('is_valid', result.is_valid)
"
```
Then check logs for lines containing `extract_hybrid:` to see native_extraction, preprocessing_time, ocr_pages, ocr_total_time, total=.

### 2. With progress callback (simulate job)
```bash
python -c "
from pathlib import Path
from app.services.pdf_extraction_service import extract_hybrid
path = Path('path/to/your_100page.pdf')
def prog(done, total):
    print(f'Extracting pages {done}/{total}')
result = extract_hybrid(path, progress_callback=prog)
print('Done. text_len=', len(result.text))
"
```

### 3. Full flow (upload + poll document status)
- Upload PDF via POST `/documents/upload`.
- Poll GET `/documents/{id}`: while `status == "processing"`, use `extracted_pages` and `total_pages` to show "Extracting pages X/Y".
- When `status == "ready"`, extraction finished; check `elapsed_time` in response.

### 4. Pytest (existing extraction tests)
```bash
cd backend
python -m pytest tests/test_pdf_extraction.py -v -k "preprocess or extract_nonexistent" --tb=short
```

### 5. Verify threshold (OCR only when native < threshold)
```bash
# Default OCR_THRESHOLD=50; set OCR_THRESHOLD=100 for "less than 100 character" rule.
# Run extraction and check logs:
# - ocr_trigger_count should be 0 or low for native-text NCERT PDFs
# - Per-page: ocr_triggered=True only when native_text_len < threshold
# - Summary: native_avg_len, ocr_pages_count, total=... (expect total <60s for 100-page NCERT)
```

---

## 1-Phase Plan (implemented)

1. **Strict OCR trigger** – `force_ocr = len(native_text.strip()) < ocr_threshold` only (default 50, env `OCR_THRESHOLD`). No image_heavy, no has_images, no garbled branch.
2. **Per-page log** – In merge loop: `page N: native_text_len=... ocr_triggered=... ocr_time=...`.
3. **Summary log** – `native_avg_len`, `ocr_pages_count`, total time breakdown (native, preprocess, ocr, final_clean).
4. **Parallel OCR** – ThreadPoolExecutor(max_workers=12) for triggered pages only.
5. **Progress** – `extract_hybrid(progress_callback=...)`; `run_extraction` updates `Document.extracted_pages` (throttled); GET `/documents/{id}` returns `extracted_pages`, `total_pages`.

---

## Projected Time (1-phase plan)

| Scenario | Before | After (threshold=50, parallel OCR) |
|----------|--------|-----------------------------------|
| 100-page NCERT (good native text) | ~283 s (OCR on all) | **<60 s** (native ~15 s, preprocess ~10 s, OCR only on few pages ~5–15 s, clean ~2 s) |
| 100-page image-heavy | ~283 s | ~40–90 s (OCR on all 100, parallel ~25–40 s) |

**Minimal diffs**: (1) Config `ocr_threshold=50` + use in `force_ocr`. (2) Parallel OCR block unchanged (already ThreadPoolExecutor). (3) Per-page log + summary with `native_avg_len`, `ocr_pages_count`. (4) Progress/cache already in place.

---

## Risks & Mitigations

- **Missed table text**: Table text is extracted by pdfplumber and appended to `page_text` **before** `final_native_len = len(page_text.strip())`, so it is included in the threshold. Pages that are mostly a table image (pdfplumber gets nothing) will have low native len and correctly get OCR. No change needed.
- **Garbled native text**: Pages with 50+ chars of garbled/mojibake text no longer get OCR (we use only the length rule). Mitigation: set `OCR_THRESHOLD=100` or higher to OCR more pages; or re-enable garbled heuristics if needed.
- **Fallback**: If extraction quality drops, set `OCR_THRESHOLD=100` in env.

---

## Optional (Not in Phase 1)

- **Text cache**: New DB field `extracted_text_json` or file path to cache extraction per document (avoid re-extraction on repeated GET /extract). Defer.
- **A/B test**: Log extraction strategy (how many pages used OCR) and outcome (e.g. MCQ count) to compare quality vs latency.

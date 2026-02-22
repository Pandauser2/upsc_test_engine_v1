# Quality baseline export + logging

Lightweight export and logging to build a quality baseline dataset. **Off by default** (env `ENABLE_EXPORT=false`).

## Config

- **ENABLE_EXPORT** (env): `true` to enable export and extra logging. Default: `false`.
- **exports_dir** (config): Directory for JSON files. Default: `./exports` (resolved under backend).

## API

- **POST /tests/generate**  
  - Optional body field: **export_result**: `true` → when generation completes and `ENABLE_EXPORT=true`, save MCQs to `backend/exports/{test_id}.json`.

## Export file shape

`exports/{test_id}.json`:

- `test_id`, `document_title`, `num_questions`, `status`, `questions_generated`, `exported_at`
- `mcqs`: array of `{ question, options, correct_option, explanation, difficulty, topic_tag, validation_result, quality_score }`

## Logging (when ENABLE_EXPORT=true)

- **mcq_generation_service**: chunks count, outline length, per-batch context length.
- **claude_impl**: raw LLM response first 500 chars per `generate_mcqs` call.

## Test command

```bash
# In .env: ENABLE_EXPORT=true
cd backend
export ENABLE_EXPORT=true   # or add to .env

# Start API, then:
curl -X POST 'http://127.0.0.1:8000/tests/generate' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"YOUR_DOC_ID","num_questions":3,"difficulty":"MEDIUM","export_result":true}'

# After completion (poll GET /tests/{test_id} until status=completed/partial):
ls backend/exports/
# => {test_id}.json should exist
cat backend/exports/*.json | head -50
```

## Affected files

- `app/config.py` – `enable_export`, `exports_dir`
- `app/schemas/test.py` – `TestGenerateRequest.export_result`
- `app/api/tests.py` – pass `export_result` in `generation_metadata`
- `app/jobs/tasks.py` – after commit, write JSON when enable_export and export_result
- `app/services/mcq_generation_service.py` – baseline logging (chunks, context length)
- `app/llm/claude_impl.py` – log raw response first 500 chars when enable_export
- `.gitignore` – ignore `backend/exports/`

## Rollback

- Set **ENABLE_EXPORT=false** (or remove from .env): no export, no extra logging.
- To remove the feature: revert the above files and drop `export_result` from request body / `generation_metadata` if desired.

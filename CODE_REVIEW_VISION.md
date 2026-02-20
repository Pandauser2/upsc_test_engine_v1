# Code Review: Vision-based MCQ pipeline and refinements

## Scope
Backend changes: vision_mcq.py, tasks.py, documents.py, tests API, schemas/test.py, models/question.py, pdf_to_images.py, export_docx.py, migration 002.

---

### ✅ Looks Good

- **Logging** — All modules use `logging.getLogger(__name__)`; no `print()` or `console.log` in app code. Structured messages with context (batch, pages, tokens, attempt).
- **Error handling** — `run_generation` has try/except and marks test failed on error; `_claude_call_with_retry` retries with logging; `pdf_to_base64_images` catches and returns [] on failure; API uses HTTPException with clear messages.
- **Production readiness** — No TODOs or debug statements in changed code. API key from settings/env, not hardcoded.
- **Security** — Document and test APIs use `Depends(get_current_user)`; document/test access scoped by `user_id`. Inputs validated via Pydantic (num_questions 1–30, difficulty EASY/MEDIUM/HARD, options shape).
- **Architecture** — Vision pipeline in `app/llm/vision_mcq.py`; PDF→images in `app/services/pdf_to_images.py`; job in `app/jobs/tasks.py`; schemas and models in existing locations. Same BackgroundTasks, DB models, test lifecycle.
- **Validation** — `_validate_mcqs` enforces 4 or 5 options, sequential labels A–D/E, correct_answer in labels. Pre-persist validation with one retry then fail.
- **Difficulty** — Required in request; stored in `generation_metadata`; read in tasks with no default; passed into `generate_mcqs_vision`; LLM output overwritten with user difficulty in `_parse_questions_json`.

---

### ⚠️ Issues Found

- **[LOW]** [vision_mcq.py:21] — `CONCURRENT_BATCH_LIMIT = 3` is unused (batch sends are sequential for same conversation).
  - Fix: Remove the constant or document that it reserves for future use.

- **[LOW]** [alembic/versions/002_*] — Migration uses `drop_constraint` / `create_check_constraint`. SQLite does not support altering check constraints the same way; may require batch_alter_table or manual steps on SQLite.
  - Fix: If using SQLite, run migration in a batch context or document SQLite workaround; new DBs created via app get the new model constraint.

- **[LOW]** [export_docx.py:32–34] — Legacy dict path only iterates `["A","B","C","D"]`; option E would not appear if stored as dict.
  - Fix: Acceptable; new writes use list format only. Optional: add "E" to legacy loop for consistency.

---

### 📊 Summary

- **Files reviewed:** 9 (vision_mcq, tasks, documents, tests API, schemas/test, question model, pdf_to_images, export_docx, migration 002)
- **Critical issues:** 0
- **High issues:** 0
- **Medium issues:** 0
- **Low issues:** 3

# UPSC Test Engine — Backend

FastAPI app (Python 3.11): auth, documents, topics, tests, MCQ generation job, .docx export.

## Setup

1. Copy `.env.example` from project root to `backend/.env` (or set env vars).
2. Start Postgres (e.g. `docker-compose up -d` from project root).
3. Create DB and run migrations:
   ```bash
   cd backend
   pip install -r requirements.txt
   alembic upgrade head
   ```
4. Run the API:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

## Env (see root `.env.example`)

- `DATABASE_URL` — Postgres connection string.
- `SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRE_HOURS` — Auth.
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `PROMPT_VERSION`, `MAX_GENERATION_TIME_SECONDS` — LLM.
- `UPLOAD_DIR` — Directory for uploaded PDFs (default `./uploads`).

## API (all under `/`)

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `POST /documents/upload`, `POST /documents`, `GET /documents`, `GET /documents/{id}`
- `GET /topics`
- `POST /tests/generate`, `GET /tests`, `GET /tests/{id}`, `PATCH /tests/{id}`, `PATCH /tests/{id}/questions/{qid}`, `POST /tests/{id}/questions`, `POST /tests/{id}/export`

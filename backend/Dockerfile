# Render deployment steps:
# 1) Set EMBEDDING_MODEL_PATH=all-MiniLM-L6-v2 in Render environment variables
# 2) Trigger a manual deploy (build must run fresh to download model into image)
# 3) Verify in build logs: "Downloading all-MiniLM-L6-v2" appears during docker build
# 4) Verify in runtime logs: "_embedding_model: load timed out" no longer appears
# 5) Verify in runtime logs: "generate_mcqs_with_rag: embedding model ready=True"
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

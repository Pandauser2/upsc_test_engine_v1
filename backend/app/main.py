"""
FastAPI application entrypoint.
APIs are mounted from app.api (auth, documents, tests, topics, export) after Steps 3–9.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.topics import router as topics_router
from app.api.tests import router as tests_router

app = FastAPI(
    title="UPSC Test Engine API",
    description="Faculty-facing API: documents → 50 MCQs with answer, explanation, difficulty.",
    version="0.1.0",
)
# Config-based CORS origins (no wildcard in production)
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if _origins else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(topics_router)
app.include_router(tests_router)


@app.get("/health")
def health():
    """Liveness check for Docker/load balancers."""
    return {"status": "ok"}

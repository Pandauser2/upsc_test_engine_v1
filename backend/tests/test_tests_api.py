"""
API tests for tests router: POST /tests/generate validation and happy path.
Uses FastAPI TestClient with dependency overrides; creates real user and document in DB for generate flow.
Requires: fastapi, httpx (install with: pip install -r requirements.txt).
"""
import uuid

import pytest

try:
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_current_user
    from app.database import SessionLocal, init_sqlite_db
    from app.models.document import Document
    from app.models.user import User
    from app.services.auth import hash_password
    _API_DEPS_LOADED = True
except ImportError:
    _API_DEPS_LOADED = False
    TestClient = app = get_current_user = None
    SessionLocal = init_sqlite_db = Document = User = hash_password = None  # type: ignore[misc, assignment]

pytestmark = pytest.mark.skipif(
    not _API_DEPS_LOADED,
    reason="fastapi/httpx not installed (pip install -r requirements.txt)",
)


def _make_user_and_document():
    """Create a user and a ready document; return (user, document). Caller must commit and close session."""
    db = SessionLocal()
    try:
        init_sqlite_db()
        email = f"test-{uuid.uuid4().hex[:8]}@tests.example.com"
        user = User(
            email=email,
            password_hash=hash_password("testpass123"),
            role="faculty",
        )
        db.add(user)
        db.flush()
        doc = Document(
            user_id=user.id,
            source_type="pasted_text",
            title="Test doc",
            status="ready",
            extracted_text="Sample study material for UPSC. Article 1 defines India as a Union of States. " * 50,
        )
        db.add(doc)
        db.commit()
        db.refresh(user)
        db.refresh(doc)
        return user, doc
    finally:
        db.close()


@pytest.fixture
def test_user_and_doc():
    """Create one user and one ready document for tests."""
    return _make_user_and_document()


@pytest.fixture
def client_with_auth(test_user_and_doc):
    """TestClient with get_current_user overridden to return test user."""
    user, _ = test_user_and_doc

    def override_get_current_user():
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user.id).first()
            if not u:
                raise RuntimeError("Test user not found")
            return u
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_generate_validation_num_questions_too_high(client_with_auth, test_user_and_doc):
    """POST /tests/generate with num_questions=9 returns 422 (max 8)."""
    _, doc = test_user_and_doc
    r = client_with_auth.post(
        "/tests/generate",
        json={"document_id": str(doc.id), "num_questions": 9, "difficulty": "MEDIUM"},
    )
    assert r.status_code == 422
    detail = r.json().get("detail") or []
    msgs = [d.get("msg", "") for d in detail] if isinstance(detail, list) else [str(detail)]
    assert any("Maximum 8 questions" in m for m in msgs), f"Expected message in {detail}"


def test_generate_document_not_found(client_with_auth):
    """POST /tests/generate with non-existent document_id returns 404."""
    r = client_with_auth.post(
        "/tests/generate",
        json={"document_id": str(uuid.uuid4()), "num_questions": 5, "difficulty": "MEDIUM"},
    )
    assert r.status_code == 404
    assert "not found" in (r.json().get("detail") or "").lower()


def test_generate_503_when_no_gemini_key(client_with_auth, test_user_and_doc, monkeypatch):
    """POST /tests/generate returns 503 when GEMINI_API_KEY is not set."""
    import app.api.tests as tests_module
    # Patch the key resolver so env/.env does not supply a key
    monkeypatch.setattr(tests_module.settings, "gemini_api_key", "")
    from app.llm import gemini_impl
    monkeypatch.setattr(gemini_impl, "get_gemini_api_key", lambda: "")
    _, doc = test_user_and_doc
    r = client_with_auth.post(
        "/tests/generate",
        json={"document_id": str(doc.id), "num_questions": 5, "difficulty": "MEDIUM"},
    )
    assert r.status_code == 503
    assert "GEMINI_API_KEY" in (r.json().get("detail") or "")


def test_generate_success_returns_202(client_with_auth, test_user_and_doc, monkeypatch):
    """POST /tests/generate with num_questions (only place for question count) returns 202 and target_questions set."""
    import app.api.tests as tests_module
    monkeypatch.setattr(tests_module.settings, "gemini_api_key", "test-key-for-202")
    _, doc = test_user_and_doc
    r = client_with_auth.post(
        "/tests/generate",
        json={"document_id": str(doc.id), "num_questions": 3, "difficulty": "MEDIUM"},
    )
    assert r.status_code == 202, r.text
    data = r.json()
    assert "id" in data
    assert data.get("status") == "pending"
    assert data.get("document_id") == str(doc.id)
    assert data.get("target_questions") == 3


def test_generate_num_questions_8_success(client_with_auth, test_user_and_doc, monkeypatch):
    """POST /tests/generate with num_questions=8 (max) returns 202 and target_questions=8."""
    import app.api.tests as tests_module
    monkeypatch.setattr(tests_module.settings, "gemini_api_key", "test-key-for-202")
    _, doc = test_user_and_doc
    r = client_with_auth.post(
        "/tests/generate",
        json={"document_id": str(doc.id), "num_questions": 8, "difficulty": "MEDIUM"},
    )
    assert r.status_code == 202, r.text
    data = r.json()
    assert data.get("target_questions") == 8

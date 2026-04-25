import uuid
from types import SimpleNamespace

import fitz
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.services import reference_qp_service as ref_svc


def _make_pdf_bytes(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line)
        y += 14
    out = doc.tobytes()
    doc.close()
    return out


def test_compute_qp_hash_deterministic():
    data = b"same-pdf-bytes"
    h1 = ref_svc.compute_qp_hash(data)
    h2 = ref_svc.compute_qp_hash(data)
    assert h1 == h2


def test_cache_style_profile_hit_and_miss():
    qp_hash = "abc123"
    assert ref_svc.get_cached_style_profile(qp_hash) is None
    ref_svc.cache_style_profile(qp_hash, "style profile")
    assert ref_svc.get_cached_style_profile(qp_hash) == "style profile"


def test_extract_style_profile_contains_style_prompt(monkeypatch):
    pdf_bytes = _make_pdf_bytes(
        [
            "1. Which of the following statements is/are correct?",
            "A. Statement one",
            "B. Statement two",
            "2. Consider the following pairs?",
        ]
    )
    captured = {"prompt": ""}

    def fake_call(prompt_text, llm):
        captured["prompt"] = prompt_text
        return "STYLE PROFILE output"

    monkeypatch.setattr(ref_svc, "_call_style_llm", fake_call)
    out = ref_svc.extract_style_profile(pdf_bytes, llm=object())
    assert out is not None
    assert "STYLE PROFILE" in captured["prompt"]


def test_reference_qp_upload_endpoint_returns_hash(monkeypatch):
    fake_user = SimpleNamespace(id=uuid.uuid4())
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        monkeypatch.setattr("app.api.reference_qps.get_llm_service", lambda: object())
        monkeypatch.setattr(
            "app.api.reference_qps.extract_style_profile",
            lambda qp_pdf_bytes, llm: "profile",
        )
        client = TestClient(app)
        pdf_bytes = _make_pdf_bytes(["1. Question sample?"])
        files = {"file": ("reference.pdf", pdf_bytes, "application/pdf")}
        res = client.post("/reference-qps/upload", files=files, headers={"Authorization": "Bearer t"})
        assert res.status_code == 200
        body = res.json()
        assert "qp_hash" in body
        assert body["style_profile"] == "profile"
        assert body["cached"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)

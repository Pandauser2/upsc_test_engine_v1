"""Smoke/perf tests for extraction throughput and DB progress tracking."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.jobs import tasks as task_mod
from app.models.document import Document
from app.models.user import User
from app.services.pdf_extraction_service import MIN_VALID_TEXT_LEN, extract_hybrid


def _make_low_text_pdf(path: Path, pages: int = 10) -> Path:
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    doc = pymupdf.open()
    for _ in range(pages):
        p = doc.new_page()
        p.insert_text((50, 50), "x")
    doc.save(path)
    doc.close()
    return path


def test_extract_hybrid_perf_smoke_10_pages(monkeypatch, tmp_path):
    """
    Simulated scanned fixture: low-text pages trigger OCR, OCR function mocked for deterministic speed.
    Ensures pipeline produces valid text under a reasonable wall-clock budget.
    """
    pdf_path = _make_low_text_pdf(tmp_path / "scan10.pdf", pages=10)

    from app.services import pdf_extraction_service as mod

    def fake_ocr(_img, *, page_index, **kwargs):
        return f"page {page_index + 1} " + ("science polity economy history geography " * 20)

    monkeypatch.setattr(mod, "_ocr_image_with_confidence_fallback", fake_ocr)

    t0 = time.perf_counter()
    result = extract_hybrid(pdf_path)
    elapsed = time.perf_counter() - t0

    assert elapsed < 60.0
    assert result.is_valid is True
    assert len(result.text) >= MIN_VALID_TEXT_LEN


def test_run_extraction_updates_progress_page_in_db(monkeypatch, tmp_path):
    """run_extraction should persist progress_page and total_pages to documents by completion."""
    pdf_path = _make_low_text_pdf(tmp_path / "progress_job.pdf", pages=4)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    user_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    db = TestingSession()
    try:
        db.add(User(id=user_id, email="perf@example.com", password_hash="x", role="faculty"))
        db.add(
            Document(
                id=doc_id,
                user_id=user_id,
                source_type="pdf",
                filename="progress_job.pdf",
                file_path=str(pdf_path),
                file_size_bytes=pdf_path.stat().st_size,
                title="progress_job.pdf",
                status="processing",
                extracted_text="",
                total_pages=4,
                progress_page=0,
            )
        )
        db.commit()
    finally:
        db.close()

    from app.services import pdf_extraction_service as mod

    def fake_extract(_path, *, progress_callback=None, **kwargs):
        if progress_callback:
            for done in range(1, 5):
                progress_callback(done, 4)
        return mod.ExtractionResult(
            text=("policy growth environment " * 200),
            is_valid=True,
            error_message=None,
            page_count=4,
            used_ocr_pages=[0, 1, 2, 3],
        )

    monkeypatch.setattr(task_mod, "SessionLocal", TestingSession)
    monkeypatch.setattr(mod, "extract_hybrid", fake_extract)

    task_mod.run_extraction(doc_id, user_id)

    db2 = TestingSession()
    try:
        d = db2.query(Document).filter(Document.id == doc_id).first()
        assert d is not None
        assert d.status == "ready"
        assert d.total_pages == 4
        assert d.progress_page == 4
        assert len(d.extracted_text) >= MIN_VALID_TEXT_LEN
    finally:
        db2.close()

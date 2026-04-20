"""Unit tests for Document AI based PDF extraction."""
from unittest.mock import patch

import pytest

from app.services.pdf_extraction_service import ExtractionResult, extract_hybrid


@pytest.fixture
def sample_pdf(tmp_path):
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((50, 50), f"Sample page {i + 1}")
    doc.save(path)
    doc.close()
    return str(path)


def test_extract_hybrid_success(sample_pdf):
    with patch(
        "app.services.pdf_extraction_service.process_pdf_bytes",
        return_value="This is extracted text from Document AI. " * 20,
    ):
        result = extract_hybrid(sample_pdf)

    assert isinstance(result, ExtractionResult)
    assert result.is_valid is True
    assert len(result.text) >= 500
    assert result.page_count == 2


def test_extract_hybrid_document_ai_failure(sample_pdf):
    with patch(
        "app.services.pdf_extraction_service.process_pdf_bytes",
        side_effect=RuntimeError("API error"),
    ):
        result = extract_hybrid(sample_pdf)
    assert result.is_valid is False
    assert "Document AI" in (result.error_message or "")


def test_extract_hybrid_short_text(sample_pdf):
    with patch(
        "app.services.pdf_extraction_service.process_pdf_bytes",
        return_value="Too short",
    ):
        result = extract_hybrid(sample_pdf)
    assert result.is_valid is False


def test_extract_nonexistent_file():
    result = extract_hybrid("/nonexistent/file.pdf")
    assert result.is_valid is False
    assert "not found" in (result.error_message or "").lower()
    assert result.page_count == 0


def test_extract_progress_callback_reaches_total(sample_pdf):
    progress = []

    def on_progress(done: int, total: int):
        progress.append((done, total))

    with patch(
        "app.services.pdf_extraction_service.process_pdf_bytes",
        return_value="This is extracted text from Document AI. " * 20,
    ):
        result = extract_hybrid(sample_pdf, progress_callback=on_progress)

    assert result.page_count == 2
    assert progress[-1] == (2, 2)

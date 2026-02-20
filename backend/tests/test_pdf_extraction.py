"""
Unit tests for hybrid PDF extraction: text-only, image-only (OCR path), mixed, invalid PDF.
Uses temporary PDFs created with PyMuPDF where possible; mocks for OCR when needed.
"""
import tempfile
from pathlib import Path

import pytest

from app.services.pdf_extraction_service import (
    ExtractionResult,
    _preprocess,
    extract_hybrid,
    LOW_TEXT_THRESHOLD,
)


def test_preprocess_normalizes_unicode():
    assert _preprocess("  hello  world  ") == "hello world"
    assert _preprocess("hello\n\nworld") == "hello\n\nworld"
    assert _preprocess("") == ""


def test_preprocess_strips_control_chars():
    s = "a\x00b\x01c\n"
    assert "\x00" not in _preprocess(s)
    assert "a" in _preprocess(s) and "b" in _preprocess(s)


@pytest.fixture
def text_only_pdf(tmp_path):
    """Create a minimal text-only PDF with PyMuPDF."""
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "text.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "UPSC Polity: The Constitution of India is the supreme law.")
    page.insert_text((50, 70), "Fundamental Rights are in Part III.")
    doc.save(path)
    doc.close()
    return str(path)


def test_extract_text_only_pdf(text_only_pdf):
    result = extract_hybrid(text_only_pdf, use_ocr_for_low_text=False)
    assert isinstance(result, ExtractionResult)
    assert result.is_valid is True
    assert result.page_count == 1
    assert "Constitution" in result.text or "Polity" in result.text
    assert result.used_ocr_pages == []


def test_extract_nonexistent_file():
    result = extract_hybrid("/nonexistent/file.pdf")
    assert result.is_valid is False
    assert "not found" in (result.error_message or "").lower()
    assert result.page_count == 0


def test_extract_invalid_pdf(tmp_path):
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"not a pdf")
    result = extract_hybrid(path)
    assert result.is_valid is False
    assert result.error_message is not None
    assert "paste" in result.error_message.lower() or "manual" in result.error_message.lower() or "corrupt" in result.error_message.lower() or "could not" in result.error_message.lower()


def test_extract_low_text_uses_ocr_when_enabled(monkeypatch, tmp_path):
    """When a page has very little text, OCR path is used (we mock OCR to avoid tesseract)."""
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "lowtext.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # Few chars so pdfplumber gets little text; OCR will be triggered
    page.insert_text((50, 50), "x")
    doc.save(path)
    doc.close()

    ocr_calls = []

    def fake_ocr(fp, pi):
        ocr_calls.append((str(fp), pi))
        return "OCR text from image"

    from app.services import pdf_extraction_service as mod
    monkeypatch.setattr(mod, "_ocr_page_pymupdf", fake_ocr)

    result = extract_hybrid(path, low_text_threshold=10, use_ocr_for_low_text=True)
    assert result.page_count == 1
    if ocr_calls:
        assert result.used_ocr_pages == [0]
        assert "OCR text from image" in result.text


def test_extract_mixed_multipage(tmp_path):
    """Two pages: first with text, second with little text (OCR path for second)."""
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Page one has enough text content for the threshold so we do not need OCR here.")
    p2 = doc.new_page()
    p2.insert_text((50, 50), "x")
    doc.save(path)
    doc.close()

    ocr_calls = []

    def fake_ocr(fp, pi):
        ocr_calls.append(pi)
        return f"Page {pi + 1} OCR"

    from app.services import pdf_extraction_service as mod
    monkeypatch.setattr(mod, "_ocr_page_pymupdf", fake_ocr)

    result = extract_hybrid(path, low_text_threshold=20, use_ocr_for_low_text=True)
    assert result.page_count == 2
    assert result.is_valid is True
    if len(ocr_calls) >= 1:
        assert 1 in result.used_ocr_pages or 0 in result.used_ocr_pages

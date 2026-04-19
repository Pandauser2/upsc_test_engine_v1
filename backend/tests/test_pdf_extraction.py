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
    """Create a text-only PDF: enough native text to avoid image-heavy OCR (>=5000) and valid extract (>=500)."""
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "text.pdf"
    doc = pymupdf.open()
    seed = (
        "UPSC Polity: Parliament, Judiciary, Executive; Fundamental Rights Part III; "
        "DPSP Part IV; Amendment procedure Article 368; Federalism Union State relations. "
    )
    # PyMuPDF often extracts less than inserted length; overshoot so native sum clears 5000 (image-heavy gate)
    blob = seed * 90
    page = doc.new_page()
    y = 40
    step = 220
    for i in range(0, len(blob), step):
        chunk = blob[i : i + step]
        page.insert_text((40, y), chunk)
        y += 14
        if y > 780:
            page = doc.new_page()
            y = 40
    doc.save(path)
    doc.close()
    return str(path)


def test_extract_text_only_pdf(text_only_pdf):
    result = extract_hybrid(text_only_pdf, use_ocr_for_low_text=False)
    assert isinstance(result, ExtractionResult)
    assert result.is_valid is True
    assert result.page_count >= 1
    assert "Polity" in result.text or "Parliament" in result.text
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

    def fake_ocr(_img, *, page_index, **kwargs):
        ocr_calls.append(page_index)
        return "OCR text from image"

    from app.services import pdf_extraction_service as mod
    monkeypatch.setattr(mod, "_ocr_image_with_confidence_fallback", fake_ocr)

    result = extract_hybrid(path, low_text_threshold=10, use_ocr_for_low_text=True)
    assert result.page_count == 1
    if ocr_calls:
        assert result.used_ocr_pages == [0]
        assert "OCR text from image" in result.text


def test_extract_mixed_multipage(monkeypatch, tmp_path):
    """Two pages: first with text, second with little text (OCR path for second)."""
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1_long = (
        "Page one has enough text content for the threshold so we do not need OCR here. "
        * 80
    )
    y = 50
    for i in range(0, len(p1_long), 100):
        p1.insert_text((50, y), p1_long[i : i + 100])
        y += 14
    p2 = doc.new_page()
    p2.insert_text((50, 50), "x")
    doc.save(path)
    doc.close()

    ocr_calls = []

    def fake_ocr(_img, *, page_index, **kwargs):
        ocr_calls.append(page_index)
        return f"Page {page_index + 1} OCR"

    from app.services import pdf_extraction_service as mod
    monkeypatch.setattr(mod, "_ocr_image_with_confidence_fallback", fake_ocr)

    result = extract_hybrid(path, low_text_threshold=20, use_ocr_for_low_text=True)
    assert result.page_count == 2
    assert result.is_valid is True
    if len(ocr_calls) >= 1:
        assert 1 in result.used_ocr_pages or 0 in result.used_ocr_pages


def test_extract_progress_callback_reaches_total(monkeypatch, tmp_path):
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")

    path = tmp_path / "progress.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        p = doc.new_page()
        p.insert_text((50, 50), "x")
    doc.save(path)
    doc.close()

    from app.services import pdf_extraction_service as mod

    monkeypatch.setattr(
        mod,
        "_ocr_image_with_confidence_fallback",
        lambda _img, *, page_index, **kwargs: f"OCR {page_index}",
    )

    progress = []

    def on_progress(done: int, total: int):
        progress.append((done, total))

    result = extract_hybrid(path, progress_callback=on_progress)
    assert result.page_count == 3
    assert progress
    assert progress[-1] == (3, 3)


def test_per_page_failure_is_isolated(monkeypatch, tmp_path):
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")

    path = tmp_path / "partial_fail.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page()
    # Ensure enough text on page 1 so MIN_VALID_TEXT_LEN can still pass if page 2 fails.
    y = 50
    for idx in range(28):
        p1.insert_text(
            (50, y),
            f"UPSC science line {idx}: environment polity economy geography biodiversity climate energy.",
        )
        y += 18
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Page 2 will fail in native extraction path")
    doc.save(path)
    doc.close()

    from app.services import pdf_extraction_service as mod

    orig = mod._extract_page_blocks_from_page

    def flaky(page, pymupdf_module):
        if getattr(page, "number", -1) == 1:
            raise RuntimeError("synthetic per-page failure")
        return orig(page, pymupdf_module)

    monkeypatch.setattr(mod, "_extract_page_blocks_from_page", flaky)

    result = extract_hybrid(path, use_ocr_for_low_text=False)
    assert result.page_count == 2
    assert 1 in result.failed_pages
    assert result.is_valid is True

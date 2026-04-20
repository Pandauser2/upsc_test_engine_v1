"""
PDF extraction backed by Google Document AI server-side OCR.
"""
import logging
import re
from pathlib import Path
from typing import Callable, NamedTuple

logger = logging.getLogger(__name__)

# Minimum total cleaned text to consider extraction valid
MIN_VALID_TEXT_LEN = 500
# Debug sample length for before/after logging
DEBUG_SAMPLE_LEN = 300
# Short lines below this length are merged into the same paragraph (space-joined)
SHORT_LINE_CHAR_THRESHOLD = 40


class ExtractionResult(NamedTuple):
    """Result of hybrid extraction. Backward-compatible with existing callers."""

    text: str
    is_valid: bool
    error_message: str | None
    page_count: int  # same as pages_processed
    used_ocr_pages: list[int]  # 0-based page indices where OCR was applied
    failed_pages: list[int] = []


def _merge_short_lines(text: str, short_threshold: int = SHORT_LINE_CHAR_THRESHOLD) -> str:
    """
    Merge short lines into paragraphs so 'Budget\\nat\\na\\nGlance' becomes one line.
    Lines < short_threshold chars are joined with space to the previous line; else start new paragraph.
    """
    if not text or not isinstance(text, str):
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    merged: list[str] = []
    current: list[str] = []
    for line in lines:
        if len(line) < short_threshold and current:
            current[-1] = current[-1] + " " + line
        else:
            if current:
                merged.append(" ".join(current))
            current = [line]
    if current:
        merged.append(" ".join(current))
    return "\n\n".join(merged)

def _final_clean(text: str) -> str:
    """
    Deduplicate repeated lines/footnotes, merge short lines into paragraphs, normalize whitespace, ensure UTF-8.
    Log cleaned_length and before/after sample for debugging.
    """
    if not text or not isinstance(text, str):
        return ""
    before_sample = (text[:DEBUG_SAMPLE_LEN] + "…") if len(text) > DEBUG_SAMPLE_LEN else text
    lines = text.splitlines()
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(line)
        elif not stripped:
            unique.append(line)
    merged = "\n".join(unique)
    merged = _merge_short_lines(merged)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    merged = re.sub(r"[ \t]+", " ", merged)
    result = merged.strip()
    # Ensure valid UTF-8 (replace invalid surrogates / replacement chars if any)
    result = result.encode("utf-8", errors="replace").decode("utf-8")
    cleaned_length = len(result)
    after_sample = (result[:DEBUG_SAMPLE_LEN] + "…") if cleaned_length > DEBUG_SAMPLE_LEN else result
    logger.debug(
        "final_clean: cleaned_length=%s | before_sample=%s | after_sample=%s",
        cleaned_length, repr(before_sample), repr(after_sample),
    )
    return result


def extract_hybrid(
    file_path: str | Path,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
    doc_id: str | None = None,
) -> ExtractionResult:
    """Extract PDF text using Google Document AI in one request."""
    path = Path(file_path).resolve()
    if not path.exists():
        logger.warning("extract_hybrid: file not found %s", path)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message="PDF file not found.",
            page_count=0,
            used_ocr_pages=[],
            failed_pages=[],
        )

    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            page_count = len(doc)
    except ImportError as e:
        logger.warning("extract_hybrid dependencies missing: %s", e)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"Extraction dependency missing: {e!s}",
            page_count=0,
            used_ocr_pages=[],
            failed_pages=[],
        )
    except Exception as e:
        logger.exception("extract_hybrid failed to inspect PDF pages for %s: %s", path, e)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"PDF could not be read: {e!s}",
            page_count=0,
            used_ocr_pages=[],
            failed_pages=[],
        )

    try:
        pdf_bytes = path.read_bytes()
    except OSError as e:
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"Could not read PDF: {e}",
            page_count=0,
            used_ocr_pages=[],
            failed_pages=[],
        )

    try:
        full_text = process_pdf_bytes(pdf_bytes)
    except Exception as e:
        logger.error("Document AI extraction failed for %s (doc=%s): %s", path, doc_id, e)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"Document AI extraction failed: {e}",
            page_count=page_count,
            used_ocr_pages=[],
            failed_pages=[],
        )

    full_text = _final_clean(full_text)
    if progress_callback is not None:
        try:
            progress_callback(page_count, page_count)
        except Exception as cb_ex:
            logger.debug("extract_hybrid progress callback failed: %s", cb_ex)

    if not full_text or len(full_text) < MIN_VALID_TEXT_LEN:
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message="Extracted text too short or empty",
            page_count=page_count,
            used_ocr_pages=[],
            failed_pages=[],
        )

    return ExtractionResult(
        text=full_text,
        is_valid=True,
        error_message=None,
        page_count=page_count,
        used_ocr_pages=[],
        failed_pages=[],
    )


def process_pdf_bytes(pdf_bytes: bytes) -> str:
    """Local indirection for easy test mocking."""
    from app.services.document_ai_service import process_pdf_bytes as _process_pdf_bytes

    return _process_pdf_bytes(pdf_bytes)

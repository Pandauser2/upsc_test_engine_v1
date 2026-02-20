"""
Hybrid PDF extraction: pdfplumber (text + tables), PyMuPDF (image detection), pytesseract (OCR).
Preprocessing: unicodedata.normalize, strip whitespace. Invalid PDFs are flagged; fallback to pasted text.
"""
import io
import logging
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Per-page character threshold below which we treat page as image-only and run OCR
LOW_TEXT_THRESHOLD = 100


class ExtractionResult(NamedTuple):
    """Result of hybrid extraction."""

    text: str
    is_valid: bool
    error_message: str | None
    page_count: int
    used_ocr_pages: list[int]  # 0-based page indices where OCR was applied


def _preprocess(text: str) -> str:
    """Normalize Unicode (NFC), strip control chars, collapse whitespace."""
    if not text or not isinstance(text, str):
        return ""
    # NFC normalization
    text = unicodedata.normalize("NFC", text)
    # Remove control characters (except newline, tab)
    text = "".join(c for c in text if c == "\n" or c == "\t" or unicodedata.category(c) != "Cc")
    # Collapse repeated whitespace and strip
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def _extract_with_pdfplumber(file_path: str | Path) -> tuple[str, list[str], int]:
    """
    Use pdfplumber: extract_text() per page and extract_tables().
    Returns (full_text, list of per-page text for low-text detection, page_count).
    """
    import pdfplumber

    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    page_texts: list[str] = []
    all_parts: list[str] = []

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            page_parts: list[str] = []

            # Text
            t = page.extract_text()
            if t:
                page_parts.append(t)
            # Tables as text (rows joined)
            tables = page.extract_tables()
            for table in tables or []:
                for row in table or []:
                    row_text = " ".join(str(c) if c is not None else "" for c in row).strip()
                    if row_text:
                        page_parts.append(row_text)
                if table:
                    page_parts.append("")  # separator between tables

            page_text = "\n".join(page_parts)
            page_texts.append(page_text)
            all_parts.append(page_text)

        full = "\n\n".join(all_parts)
        return full, page_texts, page_count


def _page_has_images_pymupdf(file_path: str | Path, page_index: int) -> bool:
    """Check if page has notable images (e.g. for deciding OCR). PyMuPDF image list."""
    try:
        import pymupdf
        with pymupdf.open(file_path) as doc:
            if page_index >= len(doc):
                return False
            page = doc[page_index]
            return len(page.get_images()) > 0
    except Exception:
        return False


def _ocr_page_pymupdf(file_path: str | Path, page_index: int) -> str:
    """Render single page to image with PyMuPDF, run pytesseract, return text."""
    try:
        import pymupdf
        import pytesseract
    except ImportError as e:
        logger.warning("OCR dependencies missing: %s", e)
        return ""

    path = Path(file_path).resolve()
    if not path.exists():
        return ""

    try:
        with pymupdf.open(path) as doc:
            if page_index >= len(doc):
                return ""
            page = doc[page_index]
            # Render at reasonable DPI for OCR (e.g. 150)
            mat = pymupdf.Matrix(150 / 72.0, 150 / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        text = pytesseract.image_to_string(img)
        return _preprocess(text)
    except Exception as e:
        logger.warning("OCR failed for page %s: %s", page_index, e)
        return ""


def extract_hybrid(
    file_path: str | Path,
    *,
    low_text_threshold: int = LOW_TEXT_THRESHOLD,
    use_ocr_for_low_text: bool = True,
) -> ExtractionResult:
    """
    Hybrid extraction: pdfplumber text + tables; for pages with very little text, run OCR (PyMuPDF render + pytesseract).
    Returns ExtractionResult with preprocessed full text, is_valid, error_message, page_count, used_ocr_pages.
    Invalid/corrupt PDFs are flagged (is_valid=False) with a message; caller can suggest pasted-text fallback.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message="PDF file not found.",
            page_count=0,
            used_ocr_pages=[],
        )

    try:
        full_text, page_texts, page_count = _extract_with_pdfplumber(path)
    except Exception as e:
        logger.exception("pdfplumber extraction failed: %s", e)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"PDF could not be read (invalid or corrupted). You can paste the text manually: {e!s}",
            page_count=0,
            used_ocr_pages=[],
        )

    used_ocr_pages: list[int] = []
    if use_ocr_for_low_text and page_texts:
        combined_parts: list[str] = []
        for i, pt in enumerate(page_texts):
            if len(pt.strip()) < low_text_threshold:
                ocr_text = _ocr_page_pymupdf(path, i)
                if ocr_text:
                    used_ocr_pages.append(i)
                    combined_parts.append(f"[Page {i + 1} (OCR)]\n{ocr_text}")
                else:
                    combined_parts.append(pt)
            else:
                combined_parts.append(pt)
        full_text = "\n\n".join(combined_parts)

    full_text = _preprocess(full_text)
    is_valid = True
    error_message = None
    if not full_text and page_count > 0:
        is_valid = False
        error_message = "No text could be extracted. The PDF may be image-only or protected. Try pasting the text manually."

    return ExtractionResult(
        text=full_text,
        is_valid=is_valid,
        error_message=error_message,
        page_count=page_count,
        used_ocr_pages=used_ocr_pages,
    )

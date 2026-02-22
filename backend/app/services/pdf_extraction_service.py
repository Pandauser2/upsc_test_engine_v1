"""
Hybrid PDF extraction for bilingual (Hindi–English) and image-heavy PDFs (e.g. UPSC Vision IAS notes).
- Text/tables via pdfplumber; layout-aware extraction via PyMuPDF blocks.
- Aggressive OCR for image-heavy docs: native text < 5000 total or per-page < 300 or page has images.
- OpenCV preprocessing (gray, adaptive threshold, denoise) before OCR when available.
- Tesseract --oem 3 --psm 6/3, lang eng+hin; post-OCR ftfy and noise-line filter.
- Final dedupe, newline normalization, UTF-8.
"""
import io
import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import NamedTuple

try:
    import cv2
    import numpy as np
    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False

logger = logging.getLogger(__name__)

# One-time flag so we only log Tesseract install instructions once per process
_tesseract_not_installed_logged: bool = False

# Per-page: below this char count we consider OCR (or if garbled ratio high)
LOW_TEXT_THRESHOLD = 100
# Aggressive OCR: if native text per page below this, force OCR (image-heavy PDFs)
AGGRESSIVE_OCR_PAGE_THRESHOLD = 300
# If total native text (first pass) below this, treat doc as image-heavy → OCR all pages
IMAGE_HEAVY_DOC_THRESHOLD = 5000
# Post-OCR: drop lines shorter than this (noise)
OCR_MIN_LINE_LEN = 10
# Post-OCR: drop lines with more than this fraction non-alphanumeric (incl. spaces)
OCR_MAX_NONALNUM_RATIO = 0.80
# OCR DPI for image-heavy (higher = better for small text)
OCR_DPI_IMAGE_HEAVY = 350
# Garbled heuristic: if > this fraction of non-ASCII chars are outside Devanagari range, run OCR
GARBLED_RATIO_THRESHOLD = 0.30
# Latin-1 supplement (U+0080–U+00FF) ratio: if > this, page is suspected mojibake → force OCR
LATIN1_SUPPLEMENT_RATIO_THRESHOLD = 0.20
# First 2 pages (headers): force OCR if Latin-1 supplement > this (headers often garbled)
HEADER_PAGE_LATIN1_THRESHOLD = 0.10
# If page has more than this many garbled-pattern chars (É, º, ¤, etc.), trigger OCR
GARBLED_PATTERN_COUNT_THRESHOLD = 5
# Replace native page text with OCR output if OCR length >= native * this ratio
OCR_REPLACE_RATIO = 0.8
# Short lines below this length are merged into the same paragraph (space-joined)
SHORT_LINE_CHAR_THRESHOLD = 40
# Devanagari Unicode block
DEVANAGARI_START, DEVANAGARI_END = 0x0900, 0x097F
# Latin-1 supplement range (common in mojibake when UTF-8 decoded as Latin-1)
LATIN1_SUPPLEMENT_START, LATIN1_SUPPLEMENT_END = 0x80, 0xFF
# Minimum total cleaned text to consider extraction valid
MIN_VALID_TEXT_LEN = 500
# OCR render DPI for bilingual (higher = better for small script)
OCR_DPI = 300
# Debug sample length for before/after logging
DEBUG_SAMPLE_LEN = 300
# Regex for typical header mojibake chars (Indian gov PDFs): É º ¤ etc.
GARBLED_PATTERN_RE = re.compile(r"[Éº¤£ª´®ÒàÆãɪ]")

# Common Hindi mojibake sequences (font/encoding artifacts) → correct Devanagari/UTF-8.
# Header-specific and body; extend as more patterns are found in Budget/government PDFs.
DEVANAGARI_MOJIBAKE_MAP: list[tuple[str, str]] = [
    # Headers / titles
    ("ºÉiªÉàÉä´É VÉªÉiÉä", "सत्यं शिवं सुंदरं"),
    ("ºÉiªÉàÉä´É", "सत्यं"),
    ("VɪÉiÉä", "शिवं सुंदरं"),
    ("VÉªÉiÉä", "शिवं सुंदरं"),
    ("{ÉE®´É®ÉÒ", "फरवरी"),
    ("ÉÊ´VIkÉ àÉÆjÉÉãɪÉ", "वित्त मंत्रालय"),
    ("ÉÊ´VIkÉ", "वित्त"),
    ("àÉÆjÉÉãɪÉ", "मंत्रालय"),
    # Body
    ("¤ÉVÉ]", "बजट"),
    ("£ÉÉ®iÉ", "भारत"),
    ("ºÉ®BÉEÉ®", "सरकार"),
    ("ºÉÉ®", "सार"),
    ("BÉEÉ", "का"),
    ("VÉÉ®", "जार"),
    ("´ÉÉ", "क्ष"),
    ("nÚºÉÉ", "राजकोषीय"),
    ("EòÉä´É", "घाटा"),
]


class ExtractionResult(NamedTuple):
    """Result of hybrid extraction. Backward-compatible with existing callers."""

    text: str
    is_valid: bool
    error_message: str | None
    page_count: int  # same as pages_processed
    used_ocr_pages: list[int]  # 0-based page indices where OCR was applied


def _apply_devanagari_mojibake_map(text: str) -> str:
    """Apply known garbled sequences → correct Devanagari (post-ftfy). Longest first. Log if any fix applied."""
    if not text:
        return text
    original = text
    for bad, good in sorted(DEVANAGARI_MOJIBAKE_MAP, key=lambda p: -len(p[0])):
        text = text.replace(bad, good)
    if text != original:
        logger.debug("header/body mojibake map applied (custom fix)")
    return text


def _fix_mojibake(raw: str) -> str:
    """
    Fix mojibake using ftfy (fix_and_explain when available for logging), then custom Devanagari map.
    Logs raw_sample and fixed_sample (first DEBUG_SAMPLE_LEN chars) for debugging.
    """
    if not raw or not isinstance(raw, str):
        return ""
    raw_sample = (raw[:DEBUG_SAMPLE_LEN] + "…") if len(raw) > DEBUG_SAMPLE_LEN else raw
    try:
        import ftfy
        if hasattr(ftfy, "fix_and_explain"):
            cleaned, explanation = ftfy.fix_and_explain(raw)
            if explanation:
                logger.debug("ftfy fix_and_explain: %s", explanation)
        else:
            cleaned = ftfy.fix_text(raw)
    except ImportError:
        logger.warning("ftfy not installed; skipping mojibake fix. pip install ftfy")
        cleaned = raw
    cleaned = _apply_devanagari_mojibake_map(cleaned)
    fixed_sample = (cleaned[:DEBUG_SAMPLE_LEN] + "…") if len(cleaned) > DEBUG_SAMPLE_LEN else cleaned
    logger.debug(
        "mojibake: raw_sample=%s | fixed_sample=%s",
        repr(raw_sample), repr(fixed_sample),
    )
    return cleaned


def _garbled_ratio(text: str) -> float:
    """
    Heuristic: fraction of non-ASCII characters that are not in Devanagari range.
    High ratio suggests wrong encoding / mojibake; caller may trigger OCR.
    """
    if not text or not text.strip():
        return 0.0
    non_ascii = 0
    garbled = 0
    for c in text:
        if ord(c) > 127:
            non_ascii += 1
            if not (DEVANAGARI_START <= ord(c) <= DEVANAGARI_END):
                garbled += 1
    if non_ascii == 0:
        return 0.0
    return garbled / non_ascii


def _latin1_supplement_ratio(text: str) -> float:
    """Fraction of characters in U+0080–U+00FF (Latin-1 supplement). High = typical mojibake."""
    if not text or not text.strip():
        return 0.0
    n = 0
    for c in text:
        if LATIN1_SUPPLEMENT_START <= ord(c) <= LATIN1_SUPPLEMENT_END:
            n += 1
    return n / len(text)


def _devanagari_ratio(text: str) -> float:
    """Fraction of characters in Devanagari block."""
    if not text or not text.strip():
        return 0.0
    n = sum(1 for c in text if DEVANAGARI_START <= ord(c) <= DEVANAGARI_END)
    return n / len(text)


def _count_garbled_patterns(text: str) -> int:
    """Count occurrences of typical mojibake chars (É, º, ¤, etc.) from Indian gov PDFs."""
    if not text:
        return 0
    return len(GARBLED_PATTERN_RE.findall(text))


def _should_use_ocr(
    page_text: str,
    low_text_threshold: int,
    page_index: int | None = None,
) -> bool:
    """Use OCR if low text, high garbled ratio, >20% Latin-1, or header pages with >10% Latin-1, or >5 garbled patterns."""
    stripped = (page_text or "").strip()
    if len(stripped) < low_text_threshold:
        return True
    if _garbled_ratio(stripped) >= GARBLED_RATIO_THRESHOLD:
        return True
    if _latin1_supplement_ratio(stripped) >= LATIN1_SUPPLEMENT_RATIO_THRESHOLD:
        return True
    # First 2 pages (headers): force OCR if Latin-1 supplement > 10%
    if page_index is not None and page_index < 2 and _latin1_supplement_ratio(stripped) >= HEADER_PAGE_LATIN1_THRESHOLD:
        return True
    # Many garbled-pattern chars → trigger OCR
    if _count_garbled_patterns(stripped) > GARBLED_PATTERN_COUNT_THRESHOLD:
        return True
    # Non-ASCII present but almost no Devanagari → likely garbled Hindi
    if stripped and any(ord(c) > 127 for c in stripped) and _devanagari_ratio(stripped) < 0.05:
        return True
    return False


def _reduce_excessive_newlines(text: str) -> str:
    """
    Reduce excessive newlines: collapse 3+ to \\n\\n, then join non-empty lines with \\n\\n.
    """
    if not text or not isinstance(text, str):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n\n".join(lines)


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


def _preprocess(text: str) -> str:
    """Normalize Unicode (NFC), strip control chars, collapse inline spaces, then reduce excessive newlines."""
    if not text or not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFC", text)
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")
    text = re.sub(r"[ \t]+", " ", text)
    text = _reduce_excessive_newlines(text)
    return text.strip()


def _extract_page_blocks_pymupdf(file_path: Path, page_index: int) -> str:
    """
    Extract text using PyMuPDF blocks; sort by y0 then x0 for reading order (Hindi left, English right).
    Prefer get_text("blocks") (list of (x0,y0,x1,y1, text, block_no, block_type)); fallback to dict.
    """
    try:
        import pymupdf
    except ImportError:
        return ""
    path = Path(file_path).resolve()
    if not path.exists():
        return ""
    try:
        with pymupdf.open(path) as doc:
            if page_index >= len(doc):
                return ""
            page = doc[page_index]
            # Try "blocks" format first: list of (x0, y0, x1, y1, "text", block_no, block_type)
            raw_blocks = page.get_text("blocks", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
            if isinstance(raw_blocks, list) and raw_blocks:
                # Filter text blocks (block_type 0), sort by y0 then x0
                ordered: list[tuple[float, float, str]] = []
                for blk in raw_blocks:
                    if not isinstance(blk, (list, tuple)) or len(blk) < 7:
                        continue
                    x0, y0, x1, y1 = blk[0], blk[1], blk[2], blk[3]
                    text = blk[4] if isinstance(blk[4], str) else ""
                    block_type = blk[6] if len(blk) > 6 else 0
                    if block_type == 0 and text.strip():
                        ordered.append((y0, x0, text.strip()))
                if ordered:
                    ordered.sort(key=lambda t: (round(t[0], 1), t[1]))
                    return "\n\n".join(t[2] for t in ordered)
            # Fallback: get_text("dict") with blocks
            raw = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
            blocks = raw.get("blocks", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            if not blocks:
                return (page.get_text("text") or "").strip()
            ordered = []
            for blk in blocks:
                bbox = blk.get("bbox") or (0, 0, 0, 0)
                y0, x0 = bbox[1], bbox[0]
                lines_text = [
                    " ".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    for line in blk.get("lines", [])
                ]
                block_text = "\n".join(ln for ln in lines_text if ln)
                if block_text:
                    ordered.append((y0, x0, block_text))
            ordered.sort(key=lambda t: (round(t[0], 1), t[1]))
            return "\n\n".join(t[2] for t in ordered)
    except Exception as e:
        logger.warning("PyMuPDF blocks extraction failed for page %s: %s", page_index, e)
        return ""


def _extract_tables_pdfplumber(page) -> str:
    """
    Extract tables from a pdfplumber page; return markdown/CSV-like text with "Table N:" labels.
    """
    parts: list[str] = []
    try:
        tables = page.extract_tables()
        for idx, table in enumerate(tables or [], 1):
            if not table:
                continue
            rows_text: list[str] = []
            for row in table:
                cells = [str(c).strip() if c is not None else "" for c in row]
                rows_text.append(" | ".join(cells))
            if rows_text:
                parts.append(f"Table {idx}:\n" + "\n".join(rows_text))
    except Exception as e:
        logger.debug("extract_tables failed: %s", e)
    return "\n\n".join(parts) if parts else ""


def _ocr_page_pymupdf(
    file_path: Path,
    page_index: int,
    *,
    dpi: int = OCR_DPI,
    lang: str = "hin+eng",
    psm: int = 6,
    preprocess: bool = True,
) -> str:
    """
    Render page to image (dpi 300–350), optionally preprocess with OpenCV, run Tesseract.
    Config: --oem 3 (LSTM) --psm 6 (uniform block) or 3 (full page) --dpi. Post-OCR: ftfy + noise filter.
    """
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
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
            mat = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        if preprocess and _OPENCV_AVAILABLE:
            img = _preprocess_image_for_ocr(img)
        config = f"--oem 3 --psm {psm} --dpi {dpi}"
        raw_ocr = pytesseract.image_to_string(img, lang=lang, config=config)
        try:
            import ftfy
            raw_ocr = ftfy.fix_text(raw_ocr)
        except ImportError:
            pass
        cleaned = _fix_mojibake(raw_ocr)
        cleaned = _preprocess(cleaned)
        cleaned = _filter_noise_lines(cleaned)
        if len(cleaned.strip()) < 80 and psm == 6:
            config3 = f"--oem 3 --psm 3 --dpi {dpi}"
            raw_ocr3 = pytesseract.image_to_string(img, lang=lang, config=config3)
            try:
                import ftfy
                raw_ocr3 = ftfy.fix_text(raw_ocr3)
            except ImportError:
                pass
            cleaned3 = _fix_mojibake(raw_ocr3)
            cleaned3 = _preprocess(cleaned3)
            cleaned3 = _filter_noise_lines(cleaned3)
            if len(cleaned3.strip()) > len(cleaned.strip()):
                cleaned = cleaned3
                logger.debug("page %s: PSM 3 yielded more text than PSM 6", page_index + 1)
        return cleaned
    except Exception as e:
        err_msg = str(e).strip().lower()
        if "tesseract" in err_msg and ("not installed" in err_msg or "not in your path" in err_msg or "path" in err_msg):
            global _tesseract_not_installed_logged
            if not _tesseract_not_installed_logged:
                _tesseract_not_installed_logged = True
                logger.warning(
                    "Tesseract OCR is not installed or not in PATH. OCR will be skipped for image/garbled pages. "
                    "To fix: Mac: brew install tesseract tesseract-lang | Linux: sudo apt install tesseract-ocr tesseract-ocr-hin | "
                    "Then ensure 'tesseract' is on your PATH. See backend/SETUP_AND_RUN.md for details."
                )
            else:
                logger.debug("OCR skipped for page %s (Tesseract not available)", page_index)
        else:
            logger.warning("OCR failed for page %s: %s", page_index, e)
        return ""


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
    merged = _filter_noise_lines(merged)
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


def _extract_with_pdfplumber_layout(path: Path, page_index: int) -> str:
    """Single page text via pdfplumber with layout=True for better ordering."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        if page_index >= len(pdf.pages):
            return ""
        page = pdf.pages[page_index]
        t = page.extract_text(layout=True)
        return (t or "").strip()


def _page_has_images(file_path: Path, page_index: int) -> bool:
    """True if the page has any images (useful for image-heavy PDFs with overlays)."""
    try:
        import pymupdf
        with pymupdf.open(file_path) as doc:
            if page_index >= len(doc):
                return False
            images = doc[page_index].get_images()
            return len(images) > 0
    except Exception:
        return False


def _preprocess_image_for_ocr(pil_image) -> "Image.Image":
    """
    Preprocess page image for better OCR: grayscale, adaptive threshold, denoise.
    Returns PIL Image. Requires opencv-python and numpy.
    """
    if not _OPENCV_AVAILABLE:
        return pil_image
    try:
        arr = np.array(pil_image)
        if len(arr.shape) == 3:
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            gray = arr
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        denoised = cv2.medianBlur(thresh, 3)
        from PIL import Image
        return Image.fromarray(denoised)
    except Exception as e:
        logger.debug("OpenCV preprocessing failed, using original image: %s", e)
        return pil_image


def _filter_noise_lines(text: str) -> str:
    """
    Remove lines that are likely OCR noise: len < 10 or >80% non-alphanumeric.
    Dedupe consecutive identical lines, normalize newlines and spaces.
    """
    if not text or not isinstance(text, str):
        return ""
    lines = text.splitlines()
    filtered: list[str] = []
    prev = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if filtered and filtered[-1] != "":
                filtered.append("")
            continue
        if len(stripped) < OCR_MIN_LINE_LEN:
            continue
        alnum = sum(1 for c in stripped if c.isalnum() or c.isspace())
        if alnum / len(stripped) < (1.0 - OCR_MAX_NONALNUM_RATIO):
            continue
        if stripped == prev:
            continue
        prev = stripped
        filtered.append(stripped)
    merged = "\n".join(filtered)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    merged = re.sub(r"[ \t]+", " ", merged)
    return merged.strip()


def extract_hybrid(
    file_path: str | Path,
    *,
    low_text_threshold: int = LOW_TEXT_THRESHOLD,
    use_ocr_for_low_text: bool = True,
) -> ExtractionResult:
    """
    Hybrid extraction for bilingual (Hindi–English) PDFs:
    1. Per page: try PyMuPDF blocks (reading order) → fallback pdfplumber layout.
    2. Run ftfy on raw text to fix mojibake (Devanagari).
    3. Append tables from pdfplumber as "Table N:".
    4. If page is low-text or high garbled ratio: OCR with eng+hin+equ, 300 DPI; merge.
    5. Final clean: dedupe lines, normalize whitespace.
    6. If total cleaned text < MIN_VALID_TEXT_LEN → is_valid=False.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        logger.warning("extract_hybrid: file not found %s", path)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message="PDF file not found.",
            page_count=0,
            used_ocr_pages=[],
        )

    page_count = 0
    try:
        import pymupdf
        with pymupdf.open(path) as doc:
            page_count = len(doc)
    except Exception as e:
        logger.exception("PyMuPDF open failed: %s", e)
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message=f"PDF could not be read: {e!s}",
            page_count=0,
            used_ocr_pages=[],
        )

    if page_count == 0:
        return ExtractionResult(
            text="",
            is_valid=False,
            error_message="PDF has no pages.",
            page_count=0,
            used_ocr_pages=[],
        )

    # First pass: native text only to detect image-heavy docs (e.g. UPSC Vision IAS notes)
    native_per_page: list[str] = []
    for i in range(page_count):
        raw = _extract_page_blocks_pymupdf(path, i)
        if not raw.strip():
            raw = _extract_with_pdfplumber_layout(path, i)
        native_per_page.append(raw)
    total_native = sum(len(p.strip()) for p in native_per_page)
    image_heavy = total_native < IMAGE_HEAVY_DOC_THRESHOLD
    if image_heavy:
        logger.info(
            "Image-heavy PDF detected: total_native=%s < %s → OCR will run on all pages",
            total_native, IMAGE_HEAVY_DOC_THRESHOLD,
        )

    per_page_texts: list[str] = []
    used_ocr_pages: list[int] = []
    dpi_ocr = OCR_DPI_IMAGE_HEAVY if image_heavy else OCR_DPI

    for i in range(page_count):
        page_text = native_per_page[i]
        native_len = len(page_text.strip())
        raw_len = len(page_text)
        garbled_count = _count_garbled_patterns(page_text)

        page_text = _fix_mojibake(page_text)
        page_text = _preprocess(page_text)
        ftfy_len = len(page_text)

        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                if i < len(pdf.pages):
                    table_text = _extract_tables_pdfplumber(pdf.pages[i])
                    if table_text:
                        page_text = (page_text + "\n\n" + table_text).strip()
        except Exception as e:
            logger.debug("Tables extraction page %s: %s", i, e)

        final_native_len = len(page_text.strip())
        force_ocr = (
            image_heavy
            or final_native_len < AGGRESSIVE_OCR_PAGE_THRESHOLD
            or _page_has_images(path, i)
            or (use_ocr_for_low_text and _should_use_ocr(page_text, low_text_threshold, page_index=i))
        )

        ocr_len = 0
        if force_ocr:
            psm = 6 if i < 2 else 3
            ocr_text = _ocr_page_pymupdf(
                path, i, dpi=dpi_ocr, lang="hin+eng", psm=psm, preprocess=_OPENCV_AVAILABLE
            )
            if ocr_text:
                ocr_len = len(ocr_text)
                used_ocr_pages.append(i)
                if final_native_len < low_text_threshold:
                    page_text = ocr_text
                elif final_native_len > 500 and _count_garbled_patterns(page_text) <= 2:
                    pass
                elif ocr_len >= final_native_len * OCR_REPLACE_RATIO or ocr_len > final_native_len:
                    page_text = ocr_text
                    logger.debug("page %s: using OCR (native=%s ocr=%s)", i + 1, final_native_len, ocr_len)
                else:
                    page_text = page_text + "\n\n[OCR: page " + str(i + 1) + "]\n" + ocr_text

        final_len = len(page_text.strip())
        sample = (page_text[:120] + "…") if len(page_text) > 120 else page_text
        logger.debug(
            "page %s: native_len=%s ocr_len=%s final_len=%s garbled_count=%s | sample=%s",
            i + 1, raw_len, ocr_len, final_len, garbled_count, repr(sample),
        )
        per_page_texts.append(page_text)

    full_text = "\n\n".join(per_page_texts)
    raw_full = full_text
    # 5) Final cleaning: dedupe, merge short lines, normalize
    full_text = _final_clean(full_text)

    # Optional: save raw vs final to temp for manual check
    if os.environ.get("PDF_EXTRACT_DEBUG_SAVE"):
        try:
            prefix = path.stem + "_pdf_extract_"
            with tempfile.NamedTemporaryFile(mode="w", prefix=prefix, suffix="_raw.txt", delete=False, encoding="utf-8") as f:
                f.write(raw_full)
                raw_path = f.name
            with tempfile.NamedTemporaryFile(mode="w", prefix=prefix, suffix="_final.txt", delete=False, encoding="utf-8") as f:
                f.write(full_text)
                final_path = f.name
            logger.debug("PDF_EXTRACT_DEBUG_SAVE: raw=%s final=%s", raw_path, final_path)
        except Exception as e:
            logger.warning("Could not save debug extract files: %s", e)

    # Debug: raw vs cleaned length and metadata
    cleaned_length = len(full_text)
    logger.info(
        "extract_hybrid: pages=%s ocr_used_pages=%s raw_combined_len=%s cleaned_length=%s",
        page_count, used_ocr_pages, sum(len(p) for p in per_page_texts), cleaned_length,
    )
    if full_text:
        logger.debug("extract_hybrid sample (first %s): %s", DEBUG_SAMPLE_LEN, repr(full_text[:DEBUG_SAMPLE_LEN]))

    # 6) Validity: too little text → suggest vision or different file
    is_valid = bool(full_text.strip())
    error_message: str | None = None
    if not full_text.strip():
        is_valid = False
        error_message = "No text could be extracted. The PDF may be image-only or protected."
    elif len(full_text.strip()) < MIN_VALID_TEXT_LEN:
        is_valid = False
        error_message = (
            f"Extracted text is very short ({len(full_text)} chars). "
            "Try vision fallback or upload a different file."
        )

    return ExtractionResult(
        text=full_text,
        is_valid=is_valid,
        error_message=error_message,
        page_count=page_count,
        used_ocr_pages=used_ocr_pages,
    )

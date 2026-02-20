"""
Convert PDF to page images for vision-based MCQ generation.
Images are capped at MAX_DIMENSION_PX (1000px) so they comply with API limits and rate limits.
Returns list of base64-encoded PNG strings (one per page).
"""
import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DPI_TARGET = 300
# PyMuPDF default is 72 DPI; scale factor for 300 DPI
SCALE_300 = DPI_TARGET / 72.0
# Claude many-image requests: no dimension may exceed this (pixels); 800–1000 keeps under rate limits
MAX_DIMENSION_PX = 1000


def pdf_to_base64_images(file_path: str, max_pages: int | None = None) -> list[str]:
    """
    Render each PDF page as PNG at 300 DPI; if any dimension exceeds MAX_DIMENSION_PX, re-render with scaled matrix so both <= MAX_DIMENSION_PX.
    Raises FileNotFoundError if file missing. Returns [] on render failure.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    try:
        import pymupdf
    except ImportError:
        logger.error("pymupdf required for vision pipeline; pip install pymupdf")
        return []
    out: list[str] = []
    try:
        with pymupdf.open(path) as doc:
            n = len(doc)
            if max_pages is not None:
                n = min(n, max_pages)
            for i in range(n):
                page = doc[i]
                original_scale = SCALE_300
                mat = pymupdf.Matrix(original_scale, original_scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                if pix.width > MAX_DIMENSION_PX or pix.height > MAX_DIMENSION_PX:
                    scale_factor = MAX_DIMENSION_PX / max(pix.width, pix.height)
                    scale = original_scale * scale_factor
                    mat = pymupdf.Matrix(scale, scale)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                png_bytes = pix.tobytes("png")
                out.append(base64.standard_b64encode(png_bytes).decode("ascii"))
        logger.info("pdf_to_base64_images: %s pages (max %s px) from %s", len(out), MAX_DIMENSION_PX, path.name)
    except Exception as e:
        logger.exception("pdf_to_base64_images failed: %s", e)
        return []
    return out

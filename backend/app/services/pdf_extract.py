"""
PDF text extraction (text-based PDFs only for MVP).
Updates document status to ready or failed; writes extracted_text.
"""
from pathlib import Path
from PyPDF2 import PdfReader


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a text-based PDF. Raises on read errors.
    Image-only PDFs will return empty or garbage; document status should be set to failed.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts) if parts else ""

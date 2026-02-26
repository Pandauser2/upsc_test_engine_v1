#!/usr/bin/env python3
"""
Test MCQ generation with a PDF from backend/uploads.
Extracts text from the first PDF found, then runs generate_mcqs_with_rag (fast path if text < 600k).
Requires GEMINI_API_KEY in backend/.env. Run from backend: python scripts/test_generation_with_upload_pdf.py
"""
import sys
from pathlib import Path

# Ensure backend is on path and app can load
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

def main():
    uploads = _backend / "uploads"
    if not uploads.exists():
        print("uploads folder not found at", uploads)
        return 1
    pdfs = list(uploads.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in", uploads)
        return 1
    pdf_path = pdfs[0]
    print("Using PDF:", pdf_path.name)

    # Extract text
    from app.services.pdf_extraction_service import extract_hybrid
    print("Extracting text...")
    result = extract_hybrid(str(pdf_path.resolve()))
    text = (result.text or "").strip()
    if not text:
        print("Extraction produced no text.", result.error_message or "")
        return 1
    print(f"Extracted {len(text)} chars, {len(text.split())} words")

    # Generate MCQs (uses fast path if len(text) < max_single_call_chars)
    from app.services.mcq_generation_service import generate_mcqs_with_rag
    target_n = 10
    print(f"Calling generate_mcqs_with_rag (target_n={target_n})...")
    mcqs, scores, inp, out, _ = generate_mcqs_with_rag(
        text,
        topic_slugs=["polity", "geography"],
        num_questions=target_n + 3,
        target_n=target_n,
        use_rag=True,
        difficulty="medium",
    )
    print(f"Result: {len(mcqs)} MCQs (target {target_n}), input_tokens={inp}, output_tokens={out}")
    if len(mcqs) < target_n:
        print(f"Under-generated: {len(mcqs)}/{target_n}")
    for i, m in enumerate(mcqs[:3]):
        q = (m.get("question") or "")[:80]
        print(f"  {i+1}. {q}...")
    if len(mcqs) > 3:
        print(f"  ... and {len(mcqs) - 3} more")
    return 0

if __name__ == "__main__":
    sys.exit(main())

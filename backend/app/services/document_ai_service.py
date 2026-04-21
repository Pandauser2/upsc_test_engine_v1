"""
Google Document AI wrapper for server-side OCR extraction.
"""
import json
import os

import pymupdf

from app.config import settings

PROJECT_ID = "awesome-project-1-353706"
LOCATION = "us-central1"
SYNC_PROCESS_CHUNK_SIZE = 14


def _get_processor_id() -> str:
    return (
        (os.getenv("DOCUMENT_AI_PROCESSOR_ID") or "").strip()
        or (getattr(settings, "document_ai_processor_id", "") or "").strip()
    )


def _get_client():
    from google.cloud import documentai
    from google.oauth2 import service_account

    creds_json = (
        (os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON") or "").strip()
        or (getattr(settings, "google_application_credentials_json", "") or "").strip()
    )
    if not creds_json:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_JSON not set")
    creds_dict = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return documentai.DocumentProcessorServiceClient(
        credentials=credentials,
        client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"},
    )


def process_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Send PDF bytes to Document AI with page-aware chunking for sync API limits.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        total_pages = len(doc)

    if total_pages <= SYNC_PROCESS_CHUNK_SIZE:
        return _call_document_ai(pdf_bytes)

    full_text: list[str] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for start in range(0, total_pages, SYNC_PROCESS_CHUNK_SIZE):
            end = min(start + SYNC_PROCESS_CHUNK_SIZE - 1, total_pages - 1)
            with pymupdf.open() as chunk_doc:
                chunk_doc.insert_pdf(doc, from_page=start, to_page=end)
                chunk_bytes = chunk_doc.tobytes()
            chunk_text = _call_document_ai(chunk_bytes)
            if chunk_text:
                full_text.append(chunk_text)
    return "\n".join(full_text)


def _call_document_ai(pdf_bytes: bytes) -> str:
    """Call synchronous Document AI process_document for one PDF payload."""
    from google.cloud import documentai

    processor_id = _get_processor_id()
    if not processor_id:
        raise RuntimeError("DOCUMENT_AI_PROCESSOR_ID not set")

    client = _get_client()
    processor_name = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}"
        f"/processors/{processor_id}"
    )
    raw_document = documentai.RawDocument(
        content=pdf_bytes,
        mime_type="application/pdf",
    )
    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
    )
    result = client.process_document(request=request)
    return (result.document.text or "")

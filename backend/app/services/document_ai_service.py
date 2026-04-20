"""
Google Document AI wrapper for server-side OCR extraction.
"""
import json
import os

from google.cloud import documentai
from google.oauth2 import service_account

from app.config import settings

PROJECT_ID = "awesome-project-1-353706"
LOCATION = "us-central1"


def _get_processor_id() -> str:
    return (
        (os.getenv("DOCUMENT_AI_PROCESSOR_ID") or "").strip()
        or (getattr(settings, "document_ai_processor_id", "") or "").strip()
    )


def _get_client() -> documentai.DocumentProcessorServiceClient:
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
    Send raw PDF bytes to Document AI and return extracted text.
    """
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

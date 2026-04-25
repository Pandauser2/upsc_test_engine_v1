"""
Reference Question Paper upload API for optional style-guided generation.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.deps import get_current_user
from app.models.user import User
from app.llm import get_llm_service
from app.services.reference_qp_service import (
    cache_style_profile,
    compute_qp_hash,
    extract_style_profile,
    get_cached_style_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reference-qps", tags=["reference-qps"])


@router.post("/upload")
async def upload_reference_qp(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload optional reference question paper PDF and return cached/extracted style profile.
    """
    _ = current_user.id  # auth side-effect: endpoint is protected
    name = (file.filename or "").lower()
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")
    try:
        qp_pdf_bytes = await file.read()
    finally:
        await file.close()
    if not qp_pdf_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    qp_hash = compute_qp_hash(qp_pdf_bytes)
    cached_profile = get_cached_style_profile(qp_hash)
    if cached_profile is not None:
        return {"qp_hash": qp_hash, "style_profile": cached_profile, "cached": True}

    llm = get_llm_service()
    profile = extract_style_profile(qp_pdf_bytes, llm) or ""
    if profile:
        cache_style_profile(qp_hash, profile)
    else:
        logger.info("reference-qps: style extraction unavailable, continuing with default style")
    return {"qp_hash": qp_hash, "style_profile": profile, "cached": False}

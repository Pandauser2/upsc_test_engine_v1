"""
Reference Question Paper (PYQ) style extraction and in-memory caching.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import OrderedDict
from typing import Any

import fitz

logger = logging.getLogger(__name__)

_STYLE_CACHE_MAX = 20
_style_cache: OrderedDict[str, str] = OrderedDict()
_cache_lock = threading.Lock()

_STYLE_PROMPT_TEMPLATE = """You are analyzing UPSC Civil Services Prelims previous year questions.
Given these sample questions, produce a concise STYLE PROFILE (max 400 words) covering:
1. Question formats used (multi-statement, assertion-reason, match, direct, etc.)
2. Common conceptual traps (e.g. absolute statements, one-word swaps, correct-but-incomplete options)
3. Difficulty markers (how hard questions are framed linguistically)
4. Topic cluster emphasis

Output ONLY the style profile. No preamble.

Sample questions:
{sampled_questions}
"""


def compute_qp_hash(qp_pdf_bytes: bytes) -> str:
    """Return MD5 hex digest of bytes."""
    return hashlib.md5(qp_pdf_bytes).hexdigest()  # nosec - non-cryptographic cache key only


def get_cached_style_profile(qp_hash: str) -> str | None:
    """Look up style profile from in-memory LRU cache keyed by MD5 hash."""
    if not qp_hash:
        return None
    with _cache_lock:
        profile = _style_cache.get(qp_hash)
        if profile is None:
            return None
        _style_cache.move_to_end(qp_hash)
        return profile


def cache_style_profile(qp_hash: str, profile: str) -> None:
    """Store profile in LRU cache."""
    if not qp_hash or not profile:
        return
    with _cache_lock:
        _style_cache[qp_hash] = profile
        _style_cache.move_to_end(qp_hash)
        while len(_style_cache) > _STYLE_CACHE_MAX:
            _style_cache.popitem(last=False)


def _extract_qp_text(qp_pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=qp_pdf_bytes, filetype="pdf")
    pages: list[str] = []
    try:
        for page in doc:
            txt = (page.get_text("text") or "").strip()
            if txt:
                pages.append(txt)
    finally:
        doc.close()
    return "\n\n".join(pages).strip()


def _sample_questions(text: str, max_questions: int = 30) -> str:
    # First pass: explicit question marks.
    candidates = [m.strip() for m in re.findall(r"[^\n\?]{20,}\?", text)]
    # Second pass: numbered lines often used in PYQs.
    if len(candidates) < max_questions:
        numbered = re.findall(
            r"(?m)^\s*(?:Q\.?\s*)?\d{1,3}[)\].:\-]\s*(.{20,})$",
            text,
        )
        candidates.extend([n.strip() for n in numbered if n.strip()])
    # Last fallback: split on blank lines and take meaningful chunks.
    if len(candidates) < max_questions:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        candidates.extend([b for b in blocks if len(b) >= 20])

    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        norm = re.sub(r"\s+", " ", c).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
        if len(out) >= max_questions:
            break
    return "\n".join(f"{i + 1}. {q}" for i, q in enumerate(out))


def _call_style_llm(prompt_text: str, llm: Any) -> str | None:
    # Claude service path.
    if hasattr(llm, "_client") and hasattr(llm, "_model"):
        response = llm._client.messages.create(
            model=llm._model,
            max_tokens=1024,
            system="You produce concise analysis. Output only requested style profile text.",
            messages=[{"role": "user", "content": prompt_text}],
        )
        text = ""
        for block in (response.content or []):
            bt = getattr(block, "text", None)
            if bt:
                text += str(bt)
        return text.strip() or None

    # Gemini service path.
    if hasattr(llm, "_model_candidates") and hasattr(llm, "_model"):
        model_name = llm._model_candidates[0] if llm._model_candidates else "gemini-2.5-flash"
        model = llm._model(
            model_name,
            "You produce concise analysis. Output only requested style profile text.",
            with_safety=True,
        )
        response = model.generate_content(
            prompt_text,
            request_options={"timeout": 10},
        )
        try:
            out = (response.text or "").strip()
        except ValueError:
            out = ""
        return out or None

    # Mock service path for local/dev without API keys.
    if llm.__class__.__name__.lower().startswith("mock"):
        return "UPSC style: multi-statement framing, close distractors, concept traps using qualifiers, and medium-to-hard analytical emphasis."
    return None


def extract_style_profile(qp_pdf_bytes: bytes, llm) -> str | None:
    """
    Extract a compact style profile from a reference question paper.
    Returns None on parse failure, timeout, or LLM failure.
    """
    if not qp_pdf_bytes:
        return None
    try:
        text = _extract_qp_text(qp_pdf_bytes)
    except Exception as e:
        logger.warning("reference_qp: PDF parse failed: %s", e)
        return None
    if not text:
        return None
    sampled_questions = _sample_questions(text, max_questions=30)
    if not sampled_questions:
        return None
    prompt_text = _STYLE_PROMPT_TEMPLATE.format(sampled_questions=sampled_questions[:30000])

    result: dict[str, str | None] = {"profile": None}
    err: dict[str, Exception | None] = {"error": None}

    def _run() -> None:
        try:
            result["profile"] = _call_style_llm(prompt_text, llm)
        except Exception as e:
            err["error"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=10)
    if t.is_alive():
        logger.warning("reference_qp: style extraction timed out (>10s)")
        return None
    if err["error"] is not None:
        logger.warning("reference_qp: style extraction failed: %s", err["error"])
        return None
    profile = (result["profile"] or "").strip()
    if not profile:
        return None
    words = profile.split()
    if len(words) > 400:
        profile = " ".join(words[:400]).strip()
    return profile

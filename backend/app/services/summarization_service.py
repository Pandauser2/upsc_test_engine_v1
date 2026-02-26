"""
Summarization service: chunk summaries and global outline using Gemini only.
Retries on 429/529/5xx (tenacity).
"""
import logging
from typing import Callable

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Retry on rate limit, overloaded, and server errors."""
    msg = str(exc).lower()
    if "429" in str(exc) or "529" in str(exc) or "rate limit" in msg or "rate_limit" in msg:
        return True
    if "overloaded" in msg or "overloaded_error" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg:
        return True
    return False


_summarize_with_llm: Callable[[str], str] | None = None


def set_summarize_fn(fn: Callable[[str], str] | None) -> None:
    """Inject a custom summarizer (e.g. for tests)."""
    global _summarize_with_llm
    _summarize_with_llm = fn


def _call_gemini_summarize(text: str, instruction: str) -> str:
    """Call Gemini (google.genai) with instruction + text; return summary string."""
    from google import genai
    from google.genai import types
    from app.llm.gemini_impl import get_gemini_api_key, _resolve_model_name
    key = get_gemini_api_key()
    if not key:
        logger.warning("GEMINI_API_KEY not set; skipping summarization.")
        return ""
    client = genai.Client(api_key=key)
    raw = (getattr(settings, "gen_model_name", None) or "gemini-2.5-flash").strip()
    model_name = _resolve_model_name(raw)
    prompt = f"{instruction}\n\n{text[:50000]}"
    safety = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY", threshold="BLOCK_NONE"),
    ]
    config = types.GenerateContentConfig(
        system_instruction="You summarize text concisely. Output only the summary, no preamble.",
        safety_settings=safety,
        max_output_tokens=1024,
        temperature=0.2,
    )

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _create():
        return client.models.generate_content(model=model_name, contents=prompt, config=config)

    try:
        response = _create()
        raw = (getattr(response, "text", None) or "").strip()
        return raw
    except Exception as e:
        logger.warning("Gemini summarization failed after retries: %s", e)
        return ""


def _call_llm_summarize(text: str, instruction: str) -> str:
    """Call LLM (Gemini only) with instruction + text; return summary string."""
    if _summarize_with_llm is not None:
        return _summarize_with_llm(f"{instruction}\n\n{text}")
    return _call_gemini_summarize(text, instruction)


def summarize_chunk(chunk_text: str) -> str:
    """Generate a short summary of a single chunk (for RAG/context)."""
    if not chunk_text or not chunk_text.strip():
        return ""
    return _call_llm_summarize(
        chunk_text,
        "Summarize the following study material chunk in 1-3 sentences. Preserve key concepts and terms.",
    )


def generate_global_outline(chunk_summaries: list[str]) -> str:
    """Combine chunk summaries into a global document outline using Gemini."""
    if not chunk_summaries:
        return ""
    combined = "\n\n".join(f"Chunk {i+1}: {s}" for i, s in enumerate(chunk_summaries) if s)
    if not combined.strip():
        return ""
    return _call_llm_summarize(
        combined,
        "Create a short global outline (bullet points or numbered) that reflects the structure and main topics of the document. Output only the outline.",
    )

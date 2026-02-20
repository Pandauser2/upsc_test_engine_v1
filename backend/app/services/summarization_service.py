"""
Summarization service: generate chunk summaries and global outline using LLM.
Uses configured LLM provider (Claude/OpenAI) for summarization calls.
"""
import logging
from typing import Callable

from app.config import settings

logger = logging.getLogger(__name__)

# Optional: inject a custom summarizer for testing
_summarize_with_llm: Callable[[str], str] | None = None


def set_summarize_fn(fn: Callable[[str], str] | None) -> None:
    """Inject a custom summarizer (e.g. for tests)."""
    global _summarize_with_llm
    _summarize_with_llm = fn


def _call_llm_summarize(text: str, instruction: str) -> str:
    """Call LLM with instruction + text; return summary string. Uses Claude or OpenAI from settings."""
    if _summarize_with_llm is not None:
        return _summarize_with_llm(f"{instruction}\n\n{text}")

    provider = (settings.llm_provider or "claude").strip().lower()
    if provider == "openai" and (settings.openai_api_key or "").strip():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
            r = client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "You summarize text concisely. Output only the summary, no preamble."},
                    {"role": "user", "content": f"{instruction}\n\n{text[:50000]}"},
                ],
                max_tokens=1024,
            )
            if r.choices and r.choices[0].message.content:
                return r.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("OpenAI summarization failed: %s", e)
        return ""

    # Claude
    key = (settings.claude_api_key or "").strip()
    if key:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=key)
            r = client.messages.create(
                model=settings.claude_model,
                max_tokens=1024,
                system="You summarize text concisely. Output only the summary, no preamble.",
                messages=[{"role": "user", "content": f"{instruction}\n\n{text[:50000]}"}],
            )
            if r.content and len(r.content) > 0:
                return (getattr(r.content[0], "text", None) or "").strip()
        except Exception as e:
            logger.warning("Claude summarization failed: %s", e)
    return ""


def summarize_chunk(chunk_text: str) -> str:
    """Generate a short summary of a single chunk (for RAG/context)."""
    if not chunk_text or not chunk_text.strip():
        return ""
    return _call_llm_summarize(
        chunk_text,
        "Summarize the following study material chunk in 1-3 sentences. Preserve key concepts and terms.",
    )


def generate_global_outline(chunk_summaries: list[str]) -> str:
    """Combine chunk summaries into a global document outline using LLM."""
    if not chunk_summaries:
        return ""
    combined = "\n\n".join(f"Chunk {i+1}: {s}" for i, s in enumerate(chunk_summaries) if s)
    if not combined.strip():
        return ""
    return _call_llm_summarize(
        combined,
        "Create a short global outline (bullet points or numbered) that reflects the structure and main topics of the document. Output only the outline.",
    )

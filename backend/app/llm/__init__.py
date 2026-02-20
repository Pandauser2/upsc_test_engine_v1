"""
LLM abstraction: generate_mcqs(chunk, topic_slugs), validate_mcq(mcq).
Default provider is Claude (Anthropic). Set LLM_PROVIDER=openai to use OpenAI. Falls back to mock if API key unset.
"""
from app.config import settings
from app.llm.base import MCQ, LLMService


def get_llm_service():
    """Return LLM service for configured provider (claude or openai); fallback to mock if key missing."""
    provider = (settings.llm_provider or "claude").strip().lower()
    if provider == "openai":
        try:
            from app.llm.openai_impl import get_llm_service as _get
            return _get()
        except ModuleNotFoundError:
            from app.llm.mock_impl import get_mock_llm_service
            return get_mock_llm_service()
    # default: Claude (with mock fallback when key missing)
    from app.llm.claude_impl import get_llm_service as _get
    return _get()


__all__ = ["MCQ", "LLMService", "get_llm_service"]

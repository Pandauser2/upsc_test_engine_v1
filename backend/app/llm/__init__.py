"""
LLM abstraction: generate_mcqs(chunk, topic_slugs), validate_mcq(mcq).
Gemini only. Uses GEN_MODEL_NAME and GEMINI_API_KEY.
"""
import logging

from app.config import settings
from app.llm.base import MCQ, LLMService

logger = logging.getLogger(__name__)


def get_llm_service():
    """Return Gemini LLM service; mock only if API key is missing or SDK cannot be imported."""
    from app.llm.gemini_impl import get_gemini_api_key
    key = get_gemini_api_key()
    if not key:
        logger.warning("GEMINI_API_KEY not set; using mock LLM.")
        from app.llm.mock_impl import get_mock_llm_service
        return get_mock_llm_service()
    try:
        from app.llm.gemini_impl import get_llm_service as _get_gemini
        return _get_gemini()
    except ImportError as e:
        logger.warning("Gemini SDK not available, using mock: %s", e)
        from app.llm.mock_impl import get_mock_llm_service
        return get_mock_llm_service()
    except Exception as e:
        logger.exception("Gemini LLM failed: %s", e)
        raise


__all__ = ["MCQ", "LLMService", "get_llm_service"]

"""
LLM abstraction: generate_mcqs(chunk, topic_slugs), validate_mcq(mcq).
Implementations (e.g. OpenAI) in separate modules.
"""
from app.llm.base import MCQ, LLMService
from app.llm.openai_impl import get_llm_service

__all__ = ["MCQ", "LLMService", "get_llm_service"]

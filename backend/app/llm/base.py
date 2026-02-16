"""
LLM service interface: generate MCQs from text chunk, validate single MCQ.
All implementations must return topic_tag as slug from allowed list; post-parse handles unknown.
"""
from typing import Protocol


# One MCQ in the shape expected by pipeline and DB (topic_tag = slug for FK lookup).
class MCQ(Protocol):
    question: str
    options: dict  # {"A": str, "B": str, "C": str, "D": str}
    correct_option: str  # "A" | "B" | "C" | "D"
    explanation: str
    difficulty: str  # "easy" | "medium" | "hard"
    topic_tag: str  # slug from topic_list


class LLMService(Protocol):
    """Abstract interface for MCQ generation and validation."""

    def generate_mcqs(self, text_chunk: str, topic_slugs: list[str]) -> list[dict]:
        """
        Generate MCQs from one text chunk. Each dict has keys:
        question, options, correct_option, explanation, difficulty, topic_tag (slug).
        """
        ...

    def validate_mcq(self, mcq: dict) -> str:
        """Return critique string (e.g. correctness of key, clarity); stored in validation_result."""
        ...

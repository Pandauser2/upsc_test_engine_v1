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

    def generate_mcqs(
        self,
        text_chunk: str,
        topic_slugs: list[str],
        num_questions: int | None = None,
    ) -> tuple[list[dict], int, int]:
        """
        Generate MCQs from the given text (one chunk or full document).
        When num_questions is set, generate that many (e.g. for whole-document mode); else use impl default per chunk.
        Returns (mcqs, input_tokens, output_tokens). Each dict has keys:
        question, options, correct_option, explanation, difficulty, topic_tag (slug).
        """
        ...

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        """Return (critique, input_tokens, output_tokens). Critique stored in validation_result."""
        ...

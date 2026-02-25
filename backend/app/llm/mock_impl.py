"""
Mock LLM: returns placeholder MCQs when GEMINI_API_KEY is not set.
Single-call pipeline for local testing (1–25 questions).
"""
import hashlib
import logging

logger = logging.getLogger(__name__)

# User range 1–25; mock default when num_questions not provided
DEFAULT_NUM_QUESTIONS = 5


def _make_mock_mcqs(
    text_chunk: str,
    topic_slugs: list[str],
    num_questions: int,
    difficulty: str | None = None,
) -> list[dict]:
    """Generate deterministic placeholder MCQs; num_questions in 1–25."""
    if not topic_slugs:
        topic_slugs = ["polity"]
    n = max(1, min(25, num_questions))
    seed = hashlib.sha256(text_chunk[:200].encode()).hexdigest()[:8]
    diff = (difficulty or "medium").strip().lower()
    if diff not in ("easy", "medium", "hard"):
        diff = "medium"
    mcqs = []
    for i in range(n):
        slug = topic_slugs[i % len(topic_slugs)]
        mcqs.append({
            "question": f"[Mock] Question {i + 1} (seed {seed}): What is the main idea of the given text?",
            "options": {
                "A": "Option A (mock)",
                "B": "Option B (mock)",
                "C": "Option C (mock)",
                "D": "Option D (mock)",
            },
            "correct_option": ["A", "B", "C", "D"][i % 4],
            "explanation": f"Mock explanation for question {i + 1}. Set GEMINI_API_KEY in .env for real generation.",
            "difficulty": diff,
            "topic_tag": slug,
        })
    return mcqs


class MockLLMService:
    """Returns placeholder MCQs so the pipeline runs without an API key (1–25 questions per call)."""

    def generate_mcqs(
        self,
        text_chunk: str,
        topic_slugs: list[str],
        num_questions: int | None = None,
        difficulty: str | None = None,
    ) -> tuple[list[dict], int, int]:
        """Return (placeholder MCQs, fake input tokens, fake output tokens)."""
        n = num_questions if num_questions is not None else DEFAULT_NUM_QUESTIONS
        n = max(1, min(25, n))
        mcqs = _make_mock_mcqs(text_chunk, topic_slugs, n, difficulty=difficulty)
        inp = 500 + len(text_chunk) // 4
        out = 800
        return (mcqs, inp, out)

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        """Return (mock critique, 0, 0)."""
        return ("Approved (mock). Set GEMINI_API_KEY for real validation.", 0, 0)


def get_mock_llm_service() -> MockLLMService:
    return MockLLMService()

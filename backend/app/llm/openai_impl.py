"""
OpenAI implementation of LLMService: generate_mcqs and validate_mcq.
Prompt injects exact topic slugs; model must output one verbatim (post-parse maps unknown).
"""
import json
import logging
from openai import OpenAI
from app.config import settings
from app.services.prompt_helpers import format_topic_slug_instruction

logger = logging.getLogger(__name__)

# Default topic slug when model returns unknown (avoids FK errors).
DEFAULT_SLUG = "polity"

MCQ_GEN_SYSTEM = """You are an expert UPSC Prelims MCQ writer. Given a chunk of text from coaching notes, produce MCQs in valid JSON only.
Each MCQ must have: question (string), options (object with keys A, B, C, D), correct_option (one of A,B,C,D), explanation (string), difficulty (easy|medium|hard), topic_tag (exactly one slug from the allowed list).
Output a JSON array of such objects, no markdown or extra text."""

VALIDATE_SYSTEM = """You are a critic for UPSC Prelims MCQs. Review the given MCQ and respond with a short critique: is the correct answer actually correct? Is the question clear? If the key is wrong or ambiguous, say "incorrect key" or similar. Otherwise approve briefly. One paragraph only."""


def _parse_mcqs_from_response(content: str) -> list[dict]:
    """Parse JSON array from model response; return list of MCQ dicts."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
        return [data] if isinstance(data, dict) else []
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON: %s", content[:200])
        return []


def _ensure_topic_slug(mcq: dict, allowed_slugs: list[str]) -> dict:
    """Map unknown topic_tag to default slug; log for prompt tuning."""
    tag = (mcq.get("topic_tag") or "").strip().lower()
    if tag not in allowed_slugs:
        logger.info("Unknown topic_tag from model: %r; mapping to %s", tag or "(empty)", DEFAULT_SLUG)
        mcq = {**mcq, "topic_tag": DEFAULT_SLUG}
    return mcq


class OpenAILLMService:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    def generate_mcqs(self, text_chunk: str, topic_slugs: list[str]) -> tuple[list[dict], int, int]:
        """Returns (mcqs, input_tokens, output_tokens) for cost tracking."""
        topic_instruction = format_topic_slug_instruction(topic_slugs)
        user_content = f"{topic_instruction}\n\nText chunk:\n{text_chunk[:12000]}"
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MCQ_GEN_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            timeout=60.0,  # Per-request timeout (job enforces 300s total)
        )
        content = response.choices[0].message.content or "[]"
        mcqs = _parse_mcqs_from_response(content)
        usage = response.usage
        inp = (usage.prompt_tokens or 0) if usage else 0
        out = (usage.completion_tokens or 0) if usage else 0
        return ([_ensure_topic_slug(m, topic_slugs) for m in mcqs], inp, out)

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        """Returns (critique, input_tokens, output_tokens) for cost tracking."""
        import json
        blob = json.dumps(mcq, ensure_ascii=False)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": VALIDATE_SYSTEM},
                {"role": "user", "content": blob},
            ],
            temperature=0.1,
            timeout=30.0,
        )
        usage = response.usage
        inp = (usage.prompt_tokens or 0) if usage else 0
        out = (usage.completion_tokens or 0) if usage else 0
        return ((response.choices[0].message.content or "").strip(), inp, out)


def get_llm_service():
    """Return the configured LLM service (OpenAI for MVP)."""
    if settings.llm_provider != "openai":
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
    return OpenAILLMService()

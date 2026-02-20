"""
Claude (Anthropic) LLM: real MCQ generation and validation.
Uses CLAUDE_API_KEY or ANTHROPIC_API_KEY from env/settings. Falls back to mock when key is missing.
"""
import json
import logging
import os

from anthropic import Anthropic

from app.config import settings

logger = logging.getLogger(__name__)

MCQ_GEN_SYSTEM = """You are an expert UPSC Civil Services Examination question setter. The study material below may be long and span multiple pages or sections. Your task is to read the ENTIRE material and generate high-quality, conceptually rigorous MCQs suitable for UPSC Prelims.

Rules:
1. Use the ENTIRE study material—all pages and sections. Do NOT base questions only on the first page or one paragraph. Draw from different parts of the document so questions reflect the full content.
2. Focus on content that is relevant to UPSC (Polity, Economy, History, Geography, Science, Environment, etc.). Prefer substantive subject matter. Ignore or downweight meta-content (e.g. revision tips, course ads, exam strategy, cover pages, generic intro) when choosing what to test.
3. Questions must be strictly based ONLY on the provided study material. Do NOT hallucinate facts.
4. Do NOT create meta-questions about the document. Do NOT use phrases like "according to the passage" or "as stated above".
5. Test conceptual understanding, analytical reasoning, and subtle distinctions. Avoid trivial factual recall unless it tests understanding.
6. Questions must resemble actual UPSC Prelims style: multi-statement format when possible, concept-based traps, close options.
7. Provide a clear explanation that references ideas from the content.
8. topic_tag must be exactly one of the slugs provided in the user message.

Output valid JSON only, no other text: {"mcqs": [ {"question": "...", "options": {"A":"...", "B":"...", "C":"...", "D":"..."}, "correct_option": "A"|"B"|"C"|"D", "explanation": "...", "difficulty": "easy"|"medium"|"hard", "topic_tag": "<slug>"} ]}"""

MCQ_VALIDATE_SYSTEM = """You are a critic for UPSC-style MCQs. Given a question, options, correct answer, and explanation, output a short critique: Is the correct key actually correct? Is the explanation consistent with the content? Output plain text only, no JSON. If the key or explanation is wrong, say so clearly (e.g. "incorrect key" or "wrong answer"). If acceptable, say it is correct."""


def _get_api_key() -> str:
    """Resolve Claude/Anthropic API key from settings or env. Never log the key."""
    return (settings.claude_api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def get_llm_service():
    """Return Claude LLM service if API key is set; otherwise return mock."""
    key = _get_api_key()
    if not key:
        logger.warning(
            "CLAUDE_API_KEY / ANTHROPIC_API_KEY is empty or unset; using MOCK LLM. Set CLAUDE_API_KEY in backend/.env"
        )
        from app.llm.mock_impl import get_mock_llm_service
        return get_mock_llm_service()
    logger.info("Claude API key is set (len=%s); using Claude (Anthropic) API", len(key))
    return ClaudeLLMService()


class ClaudeLLMService:
    """Anthropic Messages API implementation for MCQ generation and validation."""

    def __init__(self) -> None:
        key = _get_api_key()
        self._client = Anthropic(api_key=key)
        self._model = settings.claude_model

    def generate_mcqs(
        self,
        text_chunk: str,
        topic_slugs: list[str],
        num_questions: int | None = None,
    ) -> tuple[list[dict], int, int]:
        n = num_questions if num_questions is not None else 5
        n = max(1, min(25, n))
        slugs_str = ", ".join(repr(s) for s in (topic_slugs or ["polity"]))

        user_content = f"""Topic slugs (use one verbatim for each MCQ): {slugs_str}

The study material below may contain multiple pages/sections. You MUST use the ENTIRE content—not just the first page—and draw questions from different parts. Prefer substantive UPSC subjects (polity, economy, history, geography, science, environment); avoid basing questions only on meta-content like revision tips or course descriptions. Generate exactly {n} MCQs.

--- BEGIN STUDY MATERIAL (read all of it) ---
{text_chunk[:120000]}
--- END STUDY MATERIAL ---

Generate exactly {n} MCQs from the full material above. Output valid JSON only, no other text: {{"mcqs": [ {{"question": "...", "options": {{"A":"...", "B":"...", "C":"...", "D":"..."}}, "correct_option": "A", "explanation": "...", "difficulty": "medium", "topic_tag": "<one of the slugs>}} ]}}"""

        try:
            logger.info(
                "Claude API request: model=%s, num_questions=%s, text_len=%s",
                self._model,
                n,
                len(text_chunk),
            )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=MCQ_GEN_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:
            logger.exception("Claude generate_mcqs failed: %s", e)
            raise

        inp = getattr(response.usage, "input_tokens", 0) or 0
        out = getattr(response.usage, "output_tokens", 0) or 0
        logger.info("Claude API response: input_tokens=%s, output_tokens=%s", inp, out)

        raw = ""
        if response.content and len(response.content) > 0:
            block = response.content[0]
            raw = (getattr(block, "text", None) or "").strip()
        mcqs = _parse_mcqs_json(raw, topic_slugs or ["polity"])
        return (mcqs, inp, out)

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        """Return (critique, input_tokens, output_tokens)."""
        user_content = f"""Question: {mcq.get('question', '')}
Options: {json.dumps(mcq.get('options') or {})}
Correct option: {mcq.get('correct_option', '')}
Explanation: {mcq.get('explanation', '')}

Provide a short critique. If the correct key or explanation is wrong, say so (e.g. "incorrect key"). Otherwise confirm it is correct."""

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=MCQ_VALIDATE_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
        except Exception as e:
            logger.warning("Claude validate_mcq failed: %s", e)
            return ("Validation skipped (API error).", 0, 0)

        critique = ""
        if response.content and len(response.content) > 0:
            block = response.content[0]
            critique = (getattr(block, "text", None) or "").strip()
        inp = getattr(response.usage, "input_tokens", 0) or 0
        out = getattr(response.usage, "output_tokens", 0) or 0
        return (critique, inp, out)


def _parse_mcqs_json(raw: str, topic_slugs: list[str]) -> list[dict]:
    """Parse JSON and return list of MCQ dicts. Returns [] on parse error."""
    out: list[dict] = []
    slug_set = {s.strip().lower() for s in topic_slugs} or {"polity"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("MCQ JSON parse failed: %s", e)
        return []
    items = data.get("mcqs") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(items, list):
        return []
    for m in items:
        if not isinstance(m, dict):
            continue
        question = m.get("question") or ""
        options = m.get("options")
        if not isinstance(options, dict):
            options = {"A": "", "B": "", "C": "", "D": ""}
        for k in ("A", "B", "C", "D"):
            if k not in options:
                options[k] = str(options.get(k, ""))
        correct = (m.get("correct_option") or "A").strip().upper()
        if correct not in ("A", "B", "C", "D"):
            correct = "A"
        explanation = m.get("explanation") or ""
        difficulty = (m.get("difficulty") or "medium").strip().lower()
        if difficulty not in ("easy", "medium", "hard"):
            difficulty = "medium"
        tag = (m.get("topic_tag") or "polity").strip().lower()
        if tag not in slug_set:
            tag = list(slug_set)[0] if slug_set else "polity"
        out.append({
            "question": question,
            "options": options,
            "correct_option": correct,
            "explanation": explanation,
            "difficulty": difficulty,
            "topic_tag": tag,
        })
    return out

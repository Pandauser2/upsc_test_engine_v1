"""
Gemini (Google) LLM: MCQ generation and validation via google.genai (new SDK).
Uses GEN_MODEL_NAME (e.g. gemini-2.5-flash) and GEMINI_API_KEY.
Structured JSON output for MCQs; tenacity retries on 429/500.
"""
import json
import logging
import os
import time

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 429 (rate limit) and 5xx."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "resource exhausted" in msg:
        return True
    return False


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

Output only valid JSON. No markdown, no explanations, no extra text before or after.
Strict schema: {"mcqs": [{"question": str, "options": {"A": str, "B": str, "C": str, "D": str}, "correct_option": "A"|"B"|"C"|"D", "explanation": str, "difficulty": "easy"|"medium"|"hard", "topic_tag": str}]}
Escape double quotes inside strings with backslash. Use \\n for newlines inside strings; no raw newlines in JSON."""


MCQ_VALIDATE_SYSTEM = """You are a critic for UPSC-style MCQs. Given a question, options, correct answer, and explanation, output a short critique: Is the correct key actually correct? Is the explanation consistent with the content? Output plain text only, no JSON. If the key or explanation is wrong, say so clearly (e.g. "incorrect key" or "wrong answer"). If acceptable, say it is correct."""


def _get_api_key() -> str:
    """Resolve Gemini API key from settings or env. Load backend/.env if missing (e.g. background task / worker). Never log the key."""
    key = (getattr(settings, "gemini_api_key", "") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        from pathlib import Path
        try:
            from dotenv import load_dotenv
            _backend_dir = Path(__file__).resolve().parent.parent.parent
            _env_file = _backend_dir / ".env"
            if _env_file.exists():
                load_dotenv(_env_file, override=False)
                key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        except Exception:
            pass
    return key


def get_gemini_api_key() -> str:
    """Public helper: same as _get_api_key. Use from summarization, vision, or any code that needs the key with .env fallback."""
    return _get_api_key()


# Default/fallback for generateContent (v1beta). gemini-2.0-flash no longer available to new users.
_UNSUPPORTED_MODEL_FALLBACK = "gemini-2.5-flash"
_UNSUPPORTED_MODEL_IDS = frozenset({
    "gemini-1.5-flash-002", "gemini-1.5-flash-001", "gemini-1.5-flash",
    "gemini-1.5-pro", "gemini-1.5-pro-001", "gemini-1.5-pro-002",
    "gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-2.0-flash-lite", "gemini-2.0-flash-lite-001",
})


def _resolve_model_name(name: str) -> str:
    """Return a model id that works with generateContent. Replace known-unsupported ids (e.g. from old .env)."""
    n = (name or "").strip()
    if not n:
        return _UNSUPPORTED_MODEL_FALLBACK
    if n in _UNSUPPORTED_MODEL_IDS or n.startswith("gemini-1.5-flash-") or n.startswith("gemini-1.5-pro") or n.startswith("gemini-2.0-flash"):
        logger.info("Gemini: mapping unsupported model %s -> %s", n, _UNSUPPORTED_MODEL_FALLBACK)
        return _UNSUPPORTED_MODEL_FALLBACK
    return n


def _safety_settings_none():
    """Safety settings to avoid blocking study content (google.genai types)."""
    from google.genai import types
    return [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_CIVIC_INTEGRITY", threshold="BLOCK_NONE"),
    ]


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences and leading/trailing non-JSON around the object."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    # Extract first { ... last } in case of leading/trailing text
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return t.strip()


def _parse_mcqs_json(raw: str, topic_slugs: list[str]) -> list[dict]:
    """Parse JSON and return list of MCQ dicts. Accepts correct_option or answer. Uses json_repair if available. Returns [] on parse error."""
    out: list[dict] = []
    slug_set = {s.strip().lower() for s in topic_slugs} or {"polity"}
    if not raw or not raw.strip():
        logger.warning("Gemini MCQ JSON parse: empty raw response")
        return []
    text = _strip_json_fences(raw.strip())
    data = None
    parse_error: Exception | None = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e1:
        parse_error = e1
        try:
            import json_repair
            data = json_repair.loads(text)
        except Exception:
            pass
        if data is None:
            try:
                import json_repair
                data = json_repair.loads(raw)
            except Exception:
                pass
        if data is None:
            logger.warning(
                "Gemini MCQ JSON parse failed: %s. raw response (first 2000 chars): %s",
                parse_error,
                (raw[:2000] + "..." if len(raw) > 2000 else raw),
            )
            return []
    if data is None:
        return []
    items = data.get("mcqs") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(items, list):
        return []
    for m in items:
        if not isinstance(m, dict):
            continue
        question = m.get("question") or ""
        options = m.get("options")
        if isinstance(options, list):
            labels = "ABCD"
            options = {labels[i] if i < 4 else str(i + 1): str(o.get("text", o) if isinstance(o, dict) else o) for i, o in enumerate(options[:4])}
            for k in "ABCD":
                if k not in options:
                    options[k] = ""
        if not isinstance(options, dict):
            options = {"A": "", "B": "", "C": "", "D": ""}
        for k in ("A", "B", "C", "D"):
            if k not in options:
                options[k] = str(options.get(k, ""))
        correct = (m.get("correct_option") or m.get("answer") or "A").strip().upper()
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


def get_llm_service():
    """Return Gemini LLM service if API key is set; otherwise fall back to mock."""
    key = _get_api_key()
    if not key:
        logger.warning("GEMINI_API_KEY is empty or unset; cannot use Gemini.")
        from app.llm.mock_impl import get_mock_llm_service
        return get_mock_llm_service()
    raw = (getattr(settings, "gen_model_name", "") or "gemini-2.5-flash").strip()
    model_name = _resolve_model_name(raw)
    logger.info("Using LLM: %s (Gemini)", model_name)
    return GeminiService(model_name=model_name, api_key=key)


class GeminiService:
    """Google Gemini implementation via google.genai SDK (generate_content)."""

    def __init__(self, model_name: str | None = None, api_key: str | None = None) -> None:
        from google import genai
        from google.genai import types
        key = api_key or _get_api_key()
        self._client = genai.Client(api_key=key)
        self._types = types
        raw = (model_name or getattr(settings, "gen_model_name", "gemini-2.5-flash") or "").strip()
        self._model_name = _resolve_model_name(raw)

    def generate_mcqs(
        self,
        text_chunk: str,
        topic_slugs: list[str],
        num_questions: int | None = None,
        difficulty: str | None = None,
    ) -> tuple[list[dict], int, int]:
        from google.genai import types
        n = num_questions if num_questions is not None else 5
        n = max(1, min(25, n))
        diff = (difficulty or "medium").strip().lower()
        if diff not in ("easy", "medium", "hard"):
            diff = "medium"
        slugs_str = ", ".join(repr(s) for s in (topic_slugs or ["polity"]))

        user_content = f"""Topic slugs (use one verbatim for each MCQ): {slugs_str}

Difficulty level for this run: {diff}. Generate each MCQ with difficulty set to "{diff}" in the output.

The study material below may contain multiple pages/sections. You MUST use the ENTIRE content—not just the first page—and draw questions from different parts. Generate diverse questions from different sections; avoid repeating the same concepts or very similar question stems. Prefer substantive UPSC subjects (polity, economy, history, geography, science, environment); avoid basing questions only on meta-content like revision tips or course descriptions. Generate exactly {n} MCQs.

--- BEGIN STUDY MATERIAL (read all of it) ---
{text_chunk[:120000]}
--- END STUDY MATERIAL ---

Generate exactly {n} MCQs from the full material above. Set difficulty to "{diff}" for each.
Output valid JSON only: one object with key "mcqs" and an array of objects. No markdown, no text before or after. Inside strings escape double quotes with backslash and use \\n for newlines (no raw newlines in JSON)."""

        config = types.GenerateContentConfig(
            system_instruction=MCQ_GEN_SYSTEM,
            safety_settings=_safety_settings_none(),
            max_output_tokens=4096,
            temperature=0.3,
            response_mime_type="application/json",
        )

        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )
        def _create():
            return self._client.models.generate_content(
                model=self._model_name,
                contents=user_content,
                config=config,
            )

        try:
            t_api_start = time.perf_counter()
            logger.info(
                "Gemini API request: model=%s, num_questions=%s, text_len=%s",
                self._model_name,
                n,
                len(text_chunk),
            )
            response = _create()
            logger.info("Gemini generate_mcqs API %.2fs", time.perf_counter() - t_api_start)
        except Exception as e:
            logger.exception("Gemini generate_mcqs failed: %s", e)
            raise

        raw = (getattr(response, "text", None) or "").strip()
        inp = 0
        out = 0
        um = getattr(response, "usage_metadata", None)
        if um:
            inp = getattr(um, "prompt_token_count", 0) or 0
            out = getattr(um, "candidates_token_count", 0) or getattr(um, "output_token_count", 0) or 0
        logger.info("Gemini API response: input_tokens=%s, output_tokens=%s", inp, out)

        logger.info("Gemini generate_mcqs: raw response len=%s", len(raw))
        if getattr(settings, "enable_export", False) and raw:
            logger.info("Gemini generate_mcqs: raw response (first 500 chars): %s", (raw[:500] + "..." if len(raw) > 500 else raw))
        mcqs = _parse_mcqs_json(raw, topic_slugs or ["polity"])
        # Retry once with shorter context if parse failed (e.g. unterminated string / invalid JSON)
        if len(mcqs) == 0 and raw and len(text_chunk) > 40000:
            logger.warning("Gemini generate_mcqs: parse returned 0 MCQs; retrying with shorter context (first 40k chars)")
            try:
                retry_chunk = text_chunk[:40000]
                retry_content = f"""Topic slugs: {slugs_str}. Difficulty: {diff}. Generate exactly {n} MCQs as valid JSON only.
Output a single JSON object: {{"mcqs": [{{"question":"...", "options":{{"A":"...","B":"...","C":"...","D":"..."}}, "correct_option":"A", "explanation":"...", "difficulty":"{diff}", "topic_tag":"<slug>"}}]}}
Escape quotes in strings with backslash. No newlines inside JSON strings. No other text.

--- MATERIAL ---
{retry_chunk}
--- END ---"""
                retry_response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=retry_content,
                    config=config,
                )
                retry_raw = (getattr(retry_response, "text", None) or "").strip()
                mcqs = _parse_mcqs_json(retry_raw, topic_slugs or ["polity"])
                retry_um = getattr(retry_response, "usage_metadata", None)
                if retry_um:
                    inp += getattr(retry_um, "prompt_token_count", 0) or 0
                    out += getattr(retry_um, "candidates_token_count", 0) or getattr(retry_um, "output_token_count", 0) or 0
                logger.info("Gemini generate_mcqs: retry parsed mcqs count=%s", len(mcqs))
            except Exception as retry_ex:
                logger.warning("Gemini generate_mcqs retry failed: %s", retry_ex)
        logger.info("Gemini generate_mcqs: parsed mcqs count=%s", len(mcqs))
        return (mcqs, inp, out)

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        """Return (critique, input_tokens, output_tokens)."""
        from google.genai import types
        user_content = f"""Question: {mcq.get('question', '')}
Options: {json.dumps(mcq.get('options') or {})}
Correct option: {mcq.get('correct_option', '')}
Explanation: {mcq.get('explanation', '')}

Provide a short critique. If the correct key or explanation is wrong, say so (e.g. "incorrect key"). Otherwise confirm it is correct."""

        config = types.GenerateContentConfig(
            system_instruction=MCQ_VALIDATE_SYSTEM,
            safety_settings=_safety_settings_none(),
            max_output_tokens=512,
            temperature=0.1,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=user_content,
                config=config,
            )
        except Exception as e:
            logger.warning("Gemini validate_mcq failed: %s", e)
            return ("Validation skipped (API error).", 0, 0)

        critique = (getattr(response, "text", None) or "").strip()
        inp = 0
        out = 0
        um = getattr(response, "usage_metadata", None)
        if um:
            inp = getattr(um, "prompt_token_count", 0) or 0
            out = getattr(um, "candidates_token_count", 0) or getattr(um, "output_token_count", 0) or 0
        return (critique, inp, out)

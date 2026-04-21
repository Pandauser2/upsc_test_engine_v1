"""
Google Gemini LLM for MCQ generation and validation.
Set LLM_PROVIDER=gemini and GEMINI_API_KEY (or GOOGLE_API_KEY) in backend/.env.
Uses google-generativeai; retries on 429 / resource exhausted with tenacity.
"""
import json
import logging
import os

import google.generativeai as genai
from google.generativeai.types import HarmBlockThreshold, HarmCategory
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings
from app.llm.claude_impl import MCQ_GEN_SYSTEM, MCQ_VALIDATE_SYSTEM, _parse_mcqs_json

logger = logging.getLogger(__name__)


def _safe_response_text(response: object) -> str:
    """Gemini's `.text` raises ValueError when blocked or there are no text parts."""
    try:
        t = response.text  # type: ignore[attr-defined]
    except (ValueError, AttributeError):
        return ""
    if not t:
        return ""
    return str(t).strip()


def _is_rate_limit(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "429" in s or "resource exhausted" in s or "quota" in s or "rate limit" in s


def _get_api_key() -> str:
    return (
        (settings.gemini_api_key or "").strip()
        or (os.environ.get("GEMINI_API_KEY") or "").strip()
        or (os.environ.get("GOOGLE_API_KEY") or "").strip()
    )


_DEFAULT_SAFETY = [
    {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_NONE},
    {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_NONE},
]


def _is_safety_settings_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "safety setting" in msg and ("could not understand" in msg or "unsupported" in msg)


def _is_model_not_found(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "404" in msg and ("model" in msg and ("not found" in msg or "no longer available" in msg))


def _is_timeout_error(e: Exception) -> bool:
    try:
        import google.api_core.exceptions

        if isinstance(e, google.api_core.exceptions.DeadlineExceeded):
            return True
    except ImportError:
        pass
    msg = str(e).lower()
    return "timeout" in msg or "deadline exceeded" in msg or "timed out" in msg


def get_llm_service():
    """Return Gemini service if API key is set; otherwise mock."""
    key = _get_api_key()
    if not key:
        logger.warning(
            "Gemini: No API key. Set GEMINI_API_KEY or GOOGLE_API_KEY in backend/.env (using mock)."
        )
        from app.llm.mock_impl import get_mock_llm_service

        return get_mock_llm_service()
    genai.configure(api_key=key)
    logger.info("Gemini API key is set (len=%s); using Google Generative AI", len(key))
    return GeminiLLMService()


class GeminiLLMService:
    """Gemini generateContent for MCQ generation and validation."""

    def __init__(self) -> None:
        key = _get_api_key()
        genai.configure(api_key=key)
        primary = (settings.gemini_model or "gemini-2.5-flash").strip()
        # Keep a small fallback chain so provider-side model deprecations do not hard-fail generation.
        self._model_candidates: list[str] = []
        for m in (primary, "gemini-2.5-flash", "gemini-1.5-flash"):
            mm = (m or "").strip()
            if mm and mm not in self._model_candidates:
                self._model_candidates.append(mm)

    def _model(self, model_name: str, system_instruction: str, *, with_safety: bool = True) -> genai.GenerativeModel:
        kwargs = {"system_instruction": system_instruction}
        if with_safety:
            kwargs["safety_settings"] = _DEFAULT_SAFETY
        return genai.GenerativeModel(model_name, **kwargs)

    def generate_mcqs(
        self,
        text_chunk: str,
        topic_slugs: list[str],
        num_questions: int | None = None,
        difficulty: str | None = None,
    ) -> tuple[list[dict], int, int]:
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

Generate exactly {n} MCQs from the full material above. Set difficulty to "{diff}" for each. Output valid JSON only, no other text: {{"mcqs": [ {{"question": "...", "options": {{"A":"...", "B":"...", "C":"...", "D":"..."}}, "correct_option": "A", "explanation": "...", "difficulty": "{diff}", "topic_tag": "<one of the slugs>"}} ]}}"""

        def _call_generate(model_name: str, with_safety: bool):
            model = self._model(model_name, MCQ_GEN_SYSTEM, with_safety=with_safety)

            @retry(
                retry=retry_if_exception(_is_rate_limit),
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                reraise=True,
            )
            def _gen():
                logger.info("Gemini prompt size: %d chars", len(user_content))
                return model.generate_content(
                    user_content,
                    generation_config=genai.GenerationConfig(
                        max_output_tokens=8192,
                        temperature=0.35,
                    ),
                    request_options={"timeout": 30},
                )

            return _gen()

        try:
            response = None
            chosen_model = None
            last_error: Exception | None = None
            for model_name in self._model_candidates:
                chosen_model = model_name
                logger.info(
                    "Gemini API request: model=%s, num_questions=%s, text_len=%s",
                    model_name,
                    n,
                    len(text_chunk),
                )
                try:
                    response = _call_generate(model_name, with_safety=True)
                    break
                except Exception as e:
                    if _is_timeout_error(e):
                        logger.error("Gemini timeout on model=%s, aborting fallback chain", model_name)
                        raise
                    if _is_safety_settings_error(e):
                        logger.warning(
                            "Gemini safety settings rejected by SDK/API for model=%s; retrying without custom safety settings",
                            model_name,
                        )
                        try:
                            response = _call_generate(model_name, with_safety=False)
                            break
                        except Exception as e2:
                            if _is_model_not_found(e2):
                                logger.warning("Gemini model unavailable: %s. Trying next fallback model.", model_name)
                                last_error = e2
                                continue
                            last_error = e2
                            raise
                    if _is_model_not_found(e):
                        logger.warning("Gemini model unavailable: %s. Trying next fallback model.", model_name)
                        last_error = e
                        continue
                    last_error = e
                    raise
            if response is None:
                if last_error:
                    raise last_error
                raise RuntimeError("Gemini generation returned no response")
        except Exception as e:
            logger.exception("Gemini generate_mcqs failed: %s", e)
            raise

        raw = _safe_response_text(response)
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        inp = 0
        out = 0
        um = getattr(response, "usage_metadata", None)
        if um is not None:
            inp = int(getattr(um, "prompt_token_count", 0) or 0)
            out = int(getattr(um, "candidates_token_count", 0) or 0)

        logger.info("Gemini API response: model=%s input_tokens=%s output_tokens=%s raw_len=%s", chosen_model, inp, out, len(raw))
        mcqs = _parse_mcqs_json(raw, topic_slugs or ["polity"])
        logger.info("Gemini generate_mcqs: parsed mcqs count=%s", len(mcqs))
        return (mcqs, inp, out)

    def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
        user_content = f"""Question: {mcq.get('question', '')}
Options: {json.dumps(mcq.get('options') or {})}
Correct option: {mcq.get('correct_option', '')}
Explanation: {mcq.get('explanation', '')}

Provide a short critique. If the correct key or explanation is wrong, say so (e.g. "incorrect key"). Otherwise confirm it is correct."""

        try:
            response = None
            for model_name in self._model_candidates:
                try:
                    logger.info("Gemini prompt size: %d chars", len(user_content))
                    response = self._model(model_name, MCQ_VALIDATE_SYSTEM, with_safety=True).generate_content(
                        user_content,
                        generation_config=genai.GenerationConfig(max_output_tokens=512, temperature=0.2),
                        request_options={"timeout": 30},
                    )
                    break
                except Exception as e:
                    if _is_timeout_error(e):
                        logger.error("Gemini timeout on model=%s, aborting fallback chain", model_name)
                        raise
                    if _is_safety_settings_error(e):
                        logger.warning("Gemini validate_mcq: safety settings rejected; retrying without custom safety settings")
                        try:
                            logger.info("Gemini prompt size: %d chars", len(user_content))
                            response = self._model(model_name, MCQ_VALIDATE_SYSTEM, with_safety=False).generate_content(
                                user_content,
                                generation_config=genai.GenerationConfig(max_output_tokens=512, temperature=0.2),
                                request_options={"timeout": 30},
                            )
                            break
                        except Exception as e2:
                            if _is_model_not_found(e2):
                                logger.warning("Gemini validate_mcq: model unavailable %s, trying next", model_name)
                                continue
                            logger.warning("Gemini validate_mcq failed: %s", e2)
                            return ("Validation skipped (API error).", 0, 0)
                    elif _is_model_not_found(e):
                        logger.warning("Gemini validate_mcq: model unavailable %s, trying next", model_name)
                        continue
                    else:
                        logger.warning("Gemini validate_mcq failed: %s", e)
                        return ("Validation skipped (API error).", 0, 0)
            if response is None:
                return ("Validation skipped (all configured Gemini models unavailable).", 0, 0)
        except Exception as e:
            logger.warning("Gemini validate_mcq failed: %s", e)
            return ("Validation skipped (API error).", 0, 0)

        critique = _safe_response_text(response)
        if not critique:
            return ("Validation skipped (no model output).", 0, 0)
        inp = 0
        out = 0
        um = getattr(response, "usage_metadata", None)
        if um is not None:
            inp = int(getattr(um, "prompt_token_count", 0) or 0)
            out = int(getattr(um, "candidates_token_count", 0) or 0)
        return (critique, inp, out)

    def validate_mcqs_batch(self, mcqs: list[dict]) -> tuple[list[dict], int, int]:
        user_content = (
            "Validate each MCQ in this JSON array. For each, return a validation result with: "
            "is_valid (bool), quality_score (0-1), critique (str). Return only a JSON array in the "
            "same order as input.\n\n"
            f"{json.dumps(mcqs, ensure_ascii=True)}"
        )

        response = None
        for model_name in self._model_candidates:
            try:
                logger.info("Gemini prompt size: %d chars", len(user_content))
                response = self._model(model_name, MCQ_VALIDATE_SYSTEM, with_safety=True).generate_content(
                    user_content,
                    generation_config=genai.GenerationConfig(max_output_tokens=2048, temperature=0.2),
                    request_options={"timeout": 30},
                )
                break
            except Exception as e:
                if _is_timeout_error(e):
                    logger.error("Gemini timeout on model=%s, aborting fallback chain", model_name)
                    raise
                if _is_safety_settings_error(e):
                    logger.warning("Gemini validate_mcqs_batch: safety settings rejected; retrying without custom safety settings")
                    try:
                        logger.info("Gemini prompt size: %d chars", len(user_content))
                        response = self._model(model_name, MCQ_VALIDATE_SYSTEM, with_safety=False).generate_content(
                            user_content,
                            generation_config=genai.GenerationConfig(max_output_tokens=2048, temperature=0.2),
                            request_options={"timeout": 30},
                        )
                        break
                    except Exception as e2:
                        if _is_model_not_found(e2):
                            logger.warning("Gemini validate_mcqs_batch: model unavailable %s, trying next", model_name)
                            continue
                        logger.warning("Gemini validate_mcqs_batch failed: %s", e2)
                        raise
                elif _is_model_not_found(e):
                    logger.warning("Gemini validate_mcqs_batch: model unavailable %s, trying next", model_name)
                    continue
                else:
                    logger.warning("Gemini validate_mcqs_batch failed: %s", e)
                    raise

        if response is None:
            raise RuntimeError("Gemini validate_mcqs_batch failed: all configured models unavailable")

        raw = _safe_response_text(response)
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)

        inp = 0
        out = 0
        um = getattr(response, "usage_metadata", None)
        if um is not None:
            inp = int(getattr(um, "prompt_token_count", 0) or 0)
            out = int(getattr(um, "candidates_token_count", 0) or 0)
        return _parse_batch_validation_json(raw, len(mcqs)), inp, out


def _parse_batch_validation_json(raw: str, expected_len: int) -> list[dict]:
    defaults = [{"is_valid": False, "quality_score": 0.5, "critique": ""} for _ in range(expected_len)]
    if not raw or not raw.strip():
        return defaults
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return defaults
    if not isinstance(data, list):
        return defaults
    out: list[dict] = []
    for i in range(expected_len):
        item = data[i] if i < len(data) and isinstance(data[i], dict) else {}
        is_valid = bool(item.get("is_valid", True))
        try:
            quality = float(item.get("quality_score", 0.5))
        except (TypeError, ValueError):
            quality = 0.5
        quality = max(0.0, min(1.0, quality))
        critique = str(item.get("critique", "") or "")
        out.append({"is_valid": is_valid, "quality_score": quality, "critique": critique})
    return out

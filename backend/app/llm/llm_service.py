"""
LLM service wrapper: provider fallback (primary → secondary on 429/repeated failure) and rate-limit handling.
Uses tenacity for retries on 429 and 5xx.
"""
import logging
import time
from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Rate limit: simple in-memory window (requests per minute)
_rate_limit_window: list[float] = []
_RATE_LIMIT_MAX_REQUESTS = 30
_RATE_LIMIT_WINDOW_SEC = 60


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 429 (rate limit) and 5xx-like errors."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "overloaded" in msg:
        return True
    return False


def _rate_limit_wait() -> None:
    """If we've made too many requests in the window, sleep until the window slides."""
    global _rate_limit_window
    now = time.monotonic()
    _rate_limit_window = [t for t in _rate_limit_window if now - t < _RATE_LIMIT_WINDOW_SEC]
    if len(_rate_limit_window) >= _RATE_LIMIT_MAX_REQUESTS:
        sleep_time = _RATE_LIMIT_WINDOW_SEC - (now - _rate_limit_window[0])
        if sleep_time > 0:
            logger.warning("Rate limit: sleeping %.0fs", sleep_time)
            time.sleep(sleep_time)
        _rate_limit_window = []
    _rate_limit_window.append(now)


def _call_with_retry(fn, *args, **kwargs):
    """Run fn with tenacity retry on 429/5xx."""
    _rate_limit_wait()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        reraise=True,
    )
    def _do():
        return fn(*args, **kwargs)

    return _do()


def get_llm_service_with_fallback():
    """
    Return an LLM service that uses primary provider with tenacity retries,
    and falls back to secondary provider on repeated 429/failures.
    """
    from app.config import settings
    from app.llm import get_llm_service
    from app.llm.mock_impl import get_mock_llm_service

    primary = (settings.llm_provider or "claude").strip().lower()
    secondary = "openai" if primary == "claude" else "claude"

    def _get_primary():
        return get_llm_service()

    def _get_secondary():
        if secondary == "openai":
            try:
                from app.llm.openai_impl import get_llm_service as _get
                return _get()
            except Exception as e:
                logger.debug("OpenAI fallback load failed, using mock: %s", e, exc_info=True)
                return get_mock_llm_service()
        from app.llm.claude_impl import get_llm_service as _get
        return _get()

    class _FallbackService:
        def __init__(self):
            self._primary = _get_primary()
            self._secondary = None
            self._use_secondary = False

        def _current(self):
            if self._use_secondary and self._secondary is None:
                self._secondary = _get_secondary()
                logger.info("LLM fallback: using secondary provider %s", secondary)
            return self._secondary if self._use_secondary else self._primary

        def generate_mcqs(
            self,
            text_chunk: str,
            topic_slugs: list[str],
            num_questions: int | None = None,
        ) -> tuple[list[dict], int, int]:
            try:
                return _call_with_retry(
                    self._current().generate_mcqs,
                    text_chunk,
                    topic_slugs,
                    num_questions,
                )
            except Exception as e:
                if not self._use_secondary and _is_retryable(e):
                    self._use_secondary = True
                    return _call_with_retry(
                        self._current().generate_mcqs,
                        text_chunk,
                        topic_slugs,
                        num_questions,
                    )
                raise

        def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
            try:
                return _call_with_retry(self._current().validate_mcq, mcq)
            except Exception as e:
                if not self._use_secondary and _is_retryable(e):
                    self._use_secondary = True
                    return _call_with_retry(self._current().validate_mcq, mcq)
                return ("Validation skipped (API error).", 0, 0)

    return _FallbackService()

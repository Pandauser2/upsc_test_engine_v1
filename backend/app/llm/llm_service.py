"""
LLM service wrapper: Gemini only, with tenacity retries on 429/5xx.
"""
import logging
import time

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_rate_limit_window: list[float] = []
_RATE_LIMIT_MAX_REQUESTS = 30
_RATE_LIMIT_WINDOW_SEC = 60


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 429, 529, overloaded, and 5xx-like errors."""
    msg = str(exc).lower()
    if "429" in msg or "529" in msg or "rate limit" in msg or "rate_limit" in msg:
        return True
    if "overloaded" in msg or "overloaded_error" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "resource exhausted" in msg:
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
    """Run fn with tenacity retry on 429/529/5xx."""
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
    Return Gemini LLM service with tenacity retries (no provider fallback).
    """
    from app.llm import get_llm_service

    service = get_llm_service()

    class _RetryWrapper:
        def __init__(self, inner):
            self._inner = inner

        def generate_mcqs(
            self,
            text_chunk: str,
            topic_slugs: list[str],
            num_questions: int | None = None,
        ) -> tuple[list[dict], int, int]:
            return _call_with_retry(
                self._inner.generate_mcqs,
                text_chunk,
                topic_slugs,
                num_questions,
            )

        def validate_mcq(self, mcq: dict) -> tuple[str, int, int]:
            return _call_with_retry(self._inner.validate_mcq, mcq)

    return _RetryWrapper(service)

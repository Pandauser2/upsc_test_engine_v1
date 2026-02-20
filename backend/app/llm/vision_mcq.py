"""
Vision-based MCQ generation: full-document via Claude (page images in batches).
Phase 1: Send PDF pages as image batches (same conversation).
Phase 2: Generate N MCQs from full document (one final message).
Phase 3: Quality review pass (rewrite weak questions), return corrected JSON.
"""
import json
import logging
import threading
import time
from typing import Any

from anthropic import Anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.pdf_to_images import pdf_to_base64_images

logger = logging.getLogger(__name__)

BATCH_MIN_PAGES = 1
BATCH_MAX_PAGES = 3
VISION_LLM_RETRY_ATTEMPTS = 3
CONCURRENT_BATCH_LIMIT = 3  # semaphore for in-flight batch API calls (we still append sequentially)
# Token safety: abort Phase 2 if Phase 1 already used >= this fraction of context window
CONTEXT_WINDOW_TOKENS = 200_000  # Claude Sonnet 4
TOKEN_SAFETY_THRESHOLD = 0.80
# Rate limit protection: org limit 30k input tokens/min
_ingestion_token_times: list[tuple[float, int]] = []
_ingestion_token_lock = threading.Lock()
RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX_INPUT_TOKENS = 25_000
RATE_LIMIT_SLEEP_SEC = 20

VISION_SYSTEM_INGEST = """You are an expert at reading and retaining document content. You will receive images of PDF pages in batches. Do not answer questions yet. Acknowledge briefly that you have received and noted the pages (e.g. "Received pages N to M."). Your job is to build a complete picture of the full document for the next step."""

FULL_UPSC_SYSTEM_PROMPT = """You are an expert UPSC Civil Services Examination question setter. Your task is to generate high-quality, conceptually rigorous MCQs suitable for UPSC Prelims.

Rules:
- Strictly based only on the full document provided. No hallucinations. No meta references.
- If required information is not clearly supported by the document, skip that concept rather than inventing details.
- Ensure coverage across early, middle, and later sections of the document.
- Each question must have exactly 4 or 5 options. Labels must be sequential: A, B, C, D [, E].
- Exactly one correct answer per question. correct_answer must match one of the option labels.
- Multi-statement format when appropriate. Strong conceptual traps.
- No trivial recall unless conceptually meaningful.
- If insufficient content exists, generate fewer questions rather than lowering quality.
- Do not include markdown or commentary. Return valid JSON only."""

MCQ_GEN_USER_TEMPLATE = """Generate {num_questions} UPSC Civil Services Prelims MCQs. Difficulty level for this run: {difficulty}.

{topic_slug_instruction}

Ensure questions are distributed across early, middle, and later sections of the document. Do not concentrate questions only on the last section.

Return output strictly in valid JSON.

JSON Schema:

{{
  "questions": [
    {{
      "question": "string",
      "statements": ["optional"],
      "options": [
        {{ "label": "A", "text": "string" }},
        {{ "label": "B", "text": "string" }},
        {{ "label": "C", "text": "string" }},
        {{ "label": "D", "text": "string" }}
        [optional: {{ "label": "E", "text": "string" }}]
      ],
      "correct_answer": "A",
      "explanation": "string",
      "topic_tag": "string (must be exactly one of the allowed slugs above)",
      "concepts_tested": ["optional"]
    }}
  ]
}}

Each question must have 4 or 5 options with labels A, B, C, D, and optionally E. correct_answer must be one of those labels. topic_tag must be exactly one of the allowed slugs (verbatim). Only return JSON."""

REVIEW_USER_TEMPLATE = """Review the generated MCQs for conceptual depth, weak distractors, redundancy, hallucinations, and shallow recall. Rewrite weak questions to improve UPSC-level rigor. Preserve JSON format strictly. Each question must have 4 or 5 options with labels A, B, C, D [, E]. correct_answer must match one option label. Return corrected JSON only."""


def _image_blocks(base64_images: list[str]) -> list[dict]:
    """Build content blocks for Claude: one image block per base64 string."""
    blocks: list[dict] = []
    for b64 in base64_images:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64,
            },
        })
    return blocks


def _is_retryable_vision(exc: BaseException) -> bool:
    """Retry on 429 (rate limit) and 5xx-like errors."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "overloaded" in msg:
        return True
    return False


def _claude_call_with_retry(
    client: Anthropic,
    model: str,
    system: str | None,
    messages: list[dict],
    max_tokens: int,
    context: str,
) -> tuple[str, int, int]:
    """Call client.messages.create with tenacity retry (3 attempts, 429/5xx). Returns (text, input_tokens, output_tokens)."""

    @retry(
        retry=retry_if_exception(_is_retryable_vision),
        stop=stop_after_attempt(VISION_LLM_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _do_call() -> tuple[str, int, int]:
        t0 = time.perf_counter()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
        )
        elapsed = time.perf_counter() - t0
        inp = getattr(response.usage, "input_tokens", 0) or 0
        out = getattr(response.usage, "output_tokens", 0) or 0
        text = ""
        if response.content and len(response.content) > 0:
            block = response.content[0]
            text = (getattr(block, "text", None) or "").strip()
        logger.info("%s elapsed=%.2fs input_tokens=%s output_tokens=%s", context, elapsed, inp, out)
        return (text, inp, out)

    return _do_call()


def _append_assistant_message(messages: list[dict], text: str) -> None:
    """Append assistant response to conversation."""
    messages.append({"role": "assistant", "content": [{"type": "text", "text": text}]})


def _parse_questions_json(
    raw: str,
    difficulty_override: str,
    allowed_topic_slugs: list[str] | None = None,
) -> list[dict] | None:
    """Parse Phase 2/3 JSON. Returns list of MCQ dicts; options as list [{"label":"A","text":"..."}, ...].
    difficulty from user (difficulty_override), not model. topic_tag from model; if not in allowed_topic_slugs, use default (EXPLORATION §8)."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("questions JSON parse failed: %s", e)
        return None
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        return None
    diff_lower = difficulty_override.strip().lower()
    if diff_lower not in ("easy", "medium", "hard"):
        diff_lower = "medium"
    slugs_lower = [s.strip().lower() for s in (allowed_topic_slugs or ["polity"]) if s]
    default_slug = slugs_lower[0] if slugs_lower else "polity"
    out: list[dict] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        opts = q.get("options")
        if not isinstance(opts, list):
            opts = []
        by_label: dict[str, str] = {}
        for o in opts:
            if isinstance(o, dict):
                label = (o.get("label") or "").strip().upper()
                if len(label) == 1 and label in "ABCDE":
                    by_label[label] = str(o.get("text") or "")
        ordered = ["A", "B", "C", "D", "E"]
        options_list = [{"label": L, "text": by_label.get(L, "")} for L in ordered if L in by_label]
        if len(options_list) not in (4, 5):
            continue
        options_list = options_list[:4] if len(options_list) == 4 else options_list[:5]
        correct = (q.get("correct_answer") or "A").strip().upper()[:1]
        if correct not in ("A", "B", "C", "D", "E"):
            correct = "A"
        if correct not in [x["label"] for x in options_list]:
            correct = options_list[0]["label"] if options_list else "A"
        tag = (str(q.get("topic_tag") or "").strip().lower()) or default_slug
        if tag not in slugs_lower:
            tag = default_slug
        out.append({
            "question": str(q.get("question") or ""),
            "options": options_list,
            "correct_option": correct,
            "explanation": str(q.get("explanation") or ""),
            "difficulty": diff_lower,
            "topic_tag": tag,
        })
    return out


def _validate_mcqs(mcqs: list[dict]) -> bool:
    """Validate: options count 4 or 5, labels sequential from A, exactly one correct_answer, correct_answer in labels."""
    if not mcqs:
        return False
    valid_labels_4 = ["A", "B", "C", "D"]
    valid_labels_5 = ["A", "B", "C", "D", "E"]
    for m in mcqs:
        opts = m.get("options")
        if not isinstance(opts, list) or len(opts) not in (4, 5):
            return False
        labels = [str((o.get("label") or "").strip().upper()) for o in opts if isinstance(o, dict)]
        expected = valid_labels_5 if len(opts) == 5 else valid_labels_4
        if labels != expected:
            return False
        correct = (m.get("correct_option") or "").strip().upper()
        if correct not in labels or labels.count(correct) != 1:
            return False
    return True


def generate_mcqs_vision(
    pdf_path: str,
    num_questions: int,
    difficulty: str,
    topic_slugs: list[str] | None = None,
) -> tuple[list[dict], int, int]:
    """
    Full-document vision pipeline: PDF → page images → batch ingest → generate MCQs → review pass.
    difficulty is required (EASY | MEDIUM | HARD); LLM must not decide. Returns (mcqs, total_input_tokens, total_output_tokens).
    """
    t_start = time.perf_counter()
    topic_slugs = topic_slugs or ["polity"]
    topic_slug_instruction = (
        "topic_tag must be exactly one of (output verbatim, no other value): "
        + ", ".join(topic_slugs)
    )
    key = (settings.claude_api_key or "").strip()
    if not key:
        import os
        key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise ValueError("CLAUDE_API_KEY / ANTHROPIC_API_KEY required for vision pipeline")
    client = Anthropic(api_key=key)
    model = settings.claude_model
    num_questions = max(1, min(30, num_questions))
    diff_normalized = difficulty.strip().upper()
    if diff_normalized not in ("EASY", "MEDIUM", "HARD"):
        raise ValueError("difficulty must be EASY, MEDIUM, or HARD")
    diff_for_parse = diff_normalized.lower()

    # Page images at 300 DPI
    base64_pages = pdf_to_base64_images(pdf_path)
    if not base64_pages:
        raise ValueError("No pages could be rendered from PDF")

    # Batches of 8–10 pages (last batch may be smaller)
    batches: list[list[str]] = []
    start = 0
    while start < len(base64_pages):
        size = min(BATCH_MAX_PAGES, len(base64_pages) - start)
        batches.append(base64_pages[start : start + size])
        start += size

    # Phase 1: Same conversation — send each batch, append response
    messages: list[dict[str, Any]] = []
    total_inp, total_out = 0, 0
    for batch_idx, batch in enumerate(batches):
        page_start = sum(len(b) for b in batches[:batch_idx])
        page_end = page_start + len(batch)
        content: list[dict] = _image_blocks(batch)
        # Optional short text cue
        content.append({"type": "text", "text": f"Pages {page_start + 1} to {page_end} of the document."})
        messages.append({"role": "user", "content": content})
        text, inp, out = _claude_call_with_retry(
            client, model, VISION_SYSTEM_INGEST, messages, max_tokens=256,
            context=f"vision_batch batch={batch_idx + 1} pages={page_start + 1}-{page_end}",
        )
        total_inp += inp
        total_out += out
        _append_assistant_message(messages, text)
        logger.info("Batch %s: pages %s-%s, input_tokens=%s output_tokens=%s", batch_idx + 1, page_start + 1, page_end, inp, out)
        # Hard sleep between ingestion calls to stay under 30k TPM
        time.sleep(65)
        # Rate limit protection: org limit 30k input tokens/min
        with _ingestion_token_lock:
            now = time.time()
            _ingestion_token_times.append((now, inp))
            _ingestion_token_times[:] = [(t, n) for t, n in _ingestion_token_times if t > now - RATE_LIMIT_WINDOW_SEC]
        while True:
            with _ingestion_token_lock:
                now = time.time()
                _ingestion_token_times[:] = [(t, n) for t, n in _ingestion_token_times if t > now - RATE_LIMIT_WINDOW_SEC]
                cumulative = sum(n for _, n in _ingestion_token_times)
            if cumulative <= RATE_LIMIT_MAX_INPUT_TOKENS:
                break
            logger.info("Rate limit throttle: cumulative_input_tokens=%s in last %ss > %s, sleeping %ss",
                        cumulative, RATE_LIMIT_WINDOW_SEC, RATE_LIMIT_MAX_INPUT_TOKENS, RATE_LIMIT_SLEEP_SEC)
            time.sleep(RATE_LIMIT_SLEEP_SEC)

    if total_inp >= int(CONTEXT_WINDOW_TOKENS * TOKEN_SAFETY_THRESHOLD):
        raise ValueError("Document too large for model context window")

    # Phase 2: Generate MCQs (full UPSC system prompt; inject topic slugs per EXPLORATION §0 #19, §8)
    gen_prompt = MCQ_GEN_USER_TEMPLATE.format(
        num_questions=num_questions,
        difficulty=diff_normalized,
        topic_slug_instruction=topic_slug_instruction,
    )
    messages.append({"role": "user", "content": [{"type": "text", "text": gen_prompt}]})
    gen_text, inp2, out2 = _claude_call_with_retry(
        client, model, FULL_UPSC_SYSTEM_PROMPT, messages, max_tokens=8192, context="vision_mcq_generate",
    )
    total_inp += inp2
    total_out += out2
    mcqs = _parse_questions_json(gen_text, diff_for_parse, allowed_topic_slugs=topic_slugs)
    if not mcqs:
        logger.info("vision_mcq_generate: invalid JSON, retrying once")
        messages = messages[:-1]
        messages.append({"role": "user", "content": [{"type": "text", "text": gen_prompt}]})
        gen_text2, inp2b, out2b = _claude_call_with_retry(
            client, model, FULL_UPSC_SYSTEM_PROMPT, messages, max_tokens=8192, context="vision_mcq_generate_retry",
        )
        total_inp += inp2b
        total_out += out2b
        mcqs = _parse_questions_json(gen_text2, diff_for_parse, allowed_topic_slugs=topic_slugs)
    if not mcqs:
        raise ValueError("Claude did not return valid MCQ JSON after generation and retry")

    # Phase 3: Quality review pass (full UPSC system prompt)
    review_payload = {"questions": [{"question": m["question"], "difficulty": m["difficulty"], "options": m["options"], "correct_answer": m["correct_option"], "explanation": m["explanation"]} for m in mcqs]}
    review_user = f"""{REVIEW_USER_TEMPLATE}\n\n{json.dumps(review_payload)}"""
    messages.append({"role": "user", "content": [{"type": "text", "text": review_user}]})
    review_text, inp3, out3 = _claude_call_with_retry(
        client, model, FULL_UPSC_SYSTEM_PROMPT, messages, max_tokens=8192, context="vision_mcq_review",
    )
    total_inp += inp3
    total_out += out3
    reviewed = _parse_questions_json(review_text, diff_for_parse, allowed_topic_slugs=topic_slugs)
    if reviewed:
        mcqs = reviewed

    generation_time_seconds = time.perf_counter() - t_start
    num_q = len(mcqs)
    avg_explanation = sum(len((m.get("explanation") or "")) for m in mcqs) / num_q if num_q else 0
    logger.info(
        "vision_mcq quality_metrics number_of_questions_generated=%s average_explanation_length=%.0f total_input_tokens=%s total_output_tokens=%s generation_time_seconds=%.2f",
        num_q,
        avg_explanation,
        total_inp,
        total_out,
        generation_time_seconds,
    )

    return (mcqs, total_inp, total_out)

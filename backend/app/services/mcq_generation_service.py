"""
MCQ generation service with RAG: sentence_transformers embeddings, FAISS vector store,
top-k retrieval support, single-pass generation, and batch validation with fallback.
"""
import logging
import os
import threading
import time
from typing import Any, Callable

import numpy as np

from app.config import settings
from app.llm import get_llm_service
from app.services.chunking_service import chunk_text

logger = logging.getLogger(__name__)
MAX_CONTEXT_CHUNKS = 15
BATCH_VALIDATION_MAX = 20

# Validation critique: if present (lowercased), strict gate drops the MCQ. Same list drives quality_score_from_critique.
# Kept narrow so distractor phrases like "wrong answers for B–D" do not zero the whole run.
CRITIQUE_DROP_SUBSTRINGS = (
    "incorrect key",
    "key is wrong",
    "wrong key",
    "answer key is wrong",
    "correct option is wrong",
    "marked answer is incorrect",
    "explanation is wrong",
    "explanation is incorrect",
)
LOW_QUALITY_PHRASES = CRITIQUE_DROP_SUBSTRINGS


def _embedding_model():
    """Lazy-load sentence-transformers model."""
    if not hasattr(_embedding_model, "_model"):
        model_path = (
            (settings.embedding_model_path or "").strip()
            or (os.environ.get("EMBEDDING_MODEL_PATH") or "").strip()
        )
        if not model_path:
            logger.info("_embedding_model: no path configured, skipping load")
            _embedding_model._model = None
            return _embedding_model._model

        result: dict[str, Any] = {"model": None, "error": None}

        def _load() -> None:
            try:
                from sentence_transformers import SentenceTransformer

                result["model"] = SentenceTransformer(model_path)
            except Exception as e:  # pragma: no cover - defensive, branch tested via behavior
                result["error"] = e

        t = threading.Thread(target=_load, daemon=True)
        t.start()
        t.join(timeout=10)
        if t.is_alive():
            logger.warning("_embedding_model: load timed out or failed, using uniform sampling fallback")
            _embedding_model._model = None
            return _embedding_model._model
        if result["error"] is not None:
            logger.warning("sentence_transformers not available: %s", result["error"])
            _embedding_model._model = None
            return _embedding_model._model

        try:
            _embedding_model._model = result["model"]
        except Exception as e:
            logger.warning("sentence_transformers not available: %s", e)
            _embedding_model._model = None
    return _embedding_model._model


def build_faiss_index(chunks: list[str]) -> Any:
    """
    Build FAISS index from chunk texts. Returns (index, chunk_list) for later search.
    """
    model = _embedding_model()
    if model is None or not chunks:
        return None, chunks

    try:
        import faiss
        embeddings = model.encode(chunks)
        embeddings = np.array(embeddings, dtype=np.float32)
        d = embeddings.shape[1]
        index = faiss.IndexFlatL2(d)
        index.add(embeddings)
        return index, chunks
    except Exception as e:
        logger.warning("FAISS index build failed: %s", e)
        return None, chunks


def retrieve_top_k(
    query: str,
    index: Any,
    chunk_list: list[str],
    k: int | None = None,
    max_l2_distance: float | None = None,
) -> list[str]:
    """Retrieve top-k chunks by similarity to query. If index is None, return chunks. Optional max_l2_distance filters by L2 (e.g. 0.9 ≈ cosine > 0.6)."""
    k = k or getattr(settings, "rag_top_k", 5)
    if index is None or not chunk_list:
        return chunk_list[: k * 2] if chunk_list else []

    model = _embedding_model()
    if model is None:
        return chunk_list[:k]

    max_l2 = max_l2_distance if max_l2_distance is not None else getattr(settings, "rag_relevance_max_l2", None)
    try:
        import faiss
        q = model.encode([query])
        q = np.array(q, dtype=np.float32)
        n = min(k * 2 if max_l2 is not None else k, len(chunk_list))
        distances, indices = index.search(q, n)
        out = []
        for idx, dist in zip(indices[0], distances[0]):
            if max_l2 is not None and dist > max_l2:
                continue
            if 0 <= idx < len(chunk_list):
                out.append(chunk_list[idx])
            if len(out) >= k:
                break
        return out[:k] if out else chunk_list[:k]
    except Exception as e:
        logger.warning("FAISS search failed: %s", e)
        return chunk_list[:k]


def _chunk_to_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get("text") or "")
    return str(chunk or "")


def _uniform_sample_chunks(chunks: list[Any], limit: int) -> list[Any]:
    """Pick evenly spread chunks across document order."""
    if not chunks or limit <= 0:
        return []
    if len(chunks) <= limit:
        return chunks
    step = (len(chunks) - 1) / max(1, (limit - 1))
    seen: set[int] = set()
    out: list[Any] = []
    for i in range(limit):
        idx = int(round(i * step))
        idx = max(0, min(len(chunks) - 1, idx))
        if idx in seen:
            continue
        seen.add(idx)
        out.append(chunks[idx])
    return out if out else chunks[:limit]


def retrieve_relevant_chunks(chunks: list[Any], num_questions: int, topic_tags: list[str]) -> list[Any]:
    """
    Retrieve top chunks for small-question runs.
    Uses cosine similarity against a synthetic UPSC query; falls back to uniform spread sampling.
    """
    max_context_chunks = int(getattr(settings, "max_context_chunks", MAX_CONTEXT_CHUNKS) or MAX_CONTEXT_CHUNKS)
    limit = min(max(1, num_questions * 3), max_context_chunks)
    if not chunks:
        return []
    if len(chunks) <= limit:
        return chunks

    model = _embedding_model()
    if model is None:
        return _uniform_sample_chunks(chunks, limit)

    chunk_texts = [_chunk_to_text(c) for c in chunks]
    if not any(t.strip() for t in chunk_texts):
        return _uniform_sample_chunks(chunks, limit)

    tag_text = ", ".join([t for t in topic_tags if t]) if topic_tags else "general studies"
    query = f"UPSC questions on {tag_text}: history, polity, economy concepts"

    try:
        q_emb = np.array(model.encode([query]), dtype=np.float32)[0]
        c_emb = np.array(model.encode(chunk_texts), dtype=np.float32)
    except Exception as e:
        logger.warning("retrieve_relevant_chunks: embedding encode failed, using uniform fallback: %s", e)
        return _uniform_sample_chunks(chunks, limit)

    if c_emb.ndim != 2 or c_emb.shape[0] != len(chunks):
        return _uniform_sample_chunks(chunks, limit)

    q_norm = float(np.linalg.norm(q_emb))
    c_norm = np.linalg.norm(c_emb, axis=1)
    denom = (c_norm * q_norm) + 1e-12
    sims = (c_emb @ q_emb) / denom
    ranked_idx = np.argsort(-sims)
    top_idx = ranked_idx[:limit].tolist()
    top_idx.sort()
    return [chunks[i] for i in top_idx]


def _validate_candidates_sequential(
    llm: Any,
    candidates: list[dict],
    heartbeat_callback: Callable[[], None] | None = None,
) -> tuple[list[dict], int, int]:
    """Sequential validation fallback."""
    results: list[dict] = []
    total_inp = 0
    total_out = 0
    for mcq in candidates:
        try:
            critique, ci, co = llm.validate_mcq(mcq)
            total_inp += ci
            total_out += co
            score = quality_score_from_critique(critique)
            results.append({"is_valid": True, "quality_score": score, "critique": critique})
        except Exception as e:
            logger.debug("validate_mcq failed: %s", e)
            results.append({"is_valid": False, "quality_score": 0.5, "critique": ""})
        if heartbeat_callback:
            try:
                heartbeat_callback()
            except Exception:
                pass
    return results, total_inp, total_out


def _validate_candidates(
    llm: Any,
    candidates: list[dict],
    heartbeat_callback: Callable[[], None] | None = None,
) -> tuple[list[dict], int, int]:
    """
    Batch validation path with sequential fallback on any batch failure.
    """
    if not candidates:
        return [], 0, 0
    batch_max = int(getattr(settings, "batch_validation_max", BATCH_VALIDATION_MAX) or BATCH_VALIDATION_MAX)
    batch_max = max(1, batch_max)
    try:
        total_inp = 0
        total_out = 0
        merged_results: list[dict] = []
        for start in range(0, len(candidates), batch_max):
            sub = candidates[start : start + batch_max]
            batch_results, ci, co = llm.validate_mcqs_batch(sub)
            total_inp += ci
            total_out += co
            merged_results.extend(batch_results)
            if heartbeat_callback:
                try:
                    heartbeat_callback()
                except Exception:
                    pass
        if len(merged_results) < len(candidates):
            merged_results.extend(
                [{"is_valid": False, "quality_score": 0.5, "critique": ""}] * (len(candidates) - len(merged_results))
            )
        return merged_results[: len(candidates)], total_inp, total_out
    except Exception as e:
        logger.warning("Batch validation failed; falling back to sequential validate_mcq: %s", e)
        return _validate_candidates_sequential(llm, candidates, heartbeat_callback)


def quality_score_from_critique(critique: str) -> float:
    """Score 0.0-1.0 from validation critique. Low if critique indicates wrong key/explanation."""
    if not critique or not critique.strip():
        return 0.5
    c = critique.strip().lower()
    for phrase in LOW_QUALITY_PHRASES:
        if phrase in c:
            return 0.0
    if "correct" in c and "incorrect" not in c:
        return 1.0
    return 0.7


def _mcq_minimal_shape(m: dict) -> bool:
    """Require non-trivial stem and four options so we never persist empty rows."""
    q = (m.get("question") or "").strip()
    if len(q) < 8:
        return False
    opts = m.get("options")
    if not isinstance(opts, dict):
        return False
    for k in ("A", "B", "C", "D"):
        if k not in opts or not str(opts.get(k, "")).strip():
            return False
    co = (m.get("correct_option") or "A").strip().upper()
    if co not in ("A", "B", "C", "D"):
        return False
    return True


def _sort_medium_first(mcqs: list[dict]) -> list[dict]:
    """Medium difficulty first, then easy, then hard."""

    def key(m: dict) -> int:
        d = (m.get("difficulty") or "medium").strip().lower()
        return 0 if d == "medium" else (1 if d == "easy" else 2)

    return sorted(mcqs, key=key)


def _quality_then_medium_sort_key(m: dict) -> tuple:
    """Higher quality_score first; tie-break medium > easy > hard."""
    try:
        qs = float(m.get("quality_score")) if m.get("quality_score") is not None else 0.5
    except (TypeError, ValueError):
        qs = 0.5
    d = (m.get("difficulty") or "medium").strip().lower()
    dr = 0 if d == "medium" else (1 if d == "easy" else 2)
    return (-qs, dr)


def select_mcqs_for_persistence(
    all_mcqs: list[dict],
    target_n: int,
    *,
    bad_substrings: tuple[str, ...] | None = None,
) -> tuple[list[dict], str]:
    """
    Strict gate: drop MCQs whose validation_result contains bad_substrings (key/explanation faults).
    If that removes everyone, fall back to best quality_score among well-shaped MCQs (never return zero
    when there are usable candidates — avoids false positives from validator wording).
    Returns (selected[:target_n], mode) with mode strict | quality_fallback | empty.
    """
    bad = bad_substrings if bad_substrings is not None else CRITIQUE_DROP_SUBSTRINGS
    shaped = [m for m in all_mcqs if _mcq_minimal_shape(m)]

    def _passes_critique(m: dict) -> bool:
        c = (m.get("validation_result") or "").lower()
        return not any(b in c for b in bad)

    strict = [m for m in shaped if _passes_critique(m)]
    out = _sort_medium_first(strict)[:target_n]
    if out:
        return out, "strict"

    if not shaped:
        return [], "empty"

    ranked = sorted(shaped, key=_quality_then_medium_sort_key)
    out = ranked[:target_n]
    logger.warning(
        "select_mcqs_for_persistence: strict critique gate removed all %s candidates; "
        "using quality_fallback (%s kept, target_n=%s)",
        len(shaped),
        len(out),
        target_n,
    )
    return out, "quality_fallback"


def generate_mcqs_with_rag(
    full_text: str,
    topic_slugs: list[str],
    num_questions: int,
    *,
    global_outline: str | None = None,
    use_rag: bool = True,
    batch_size: int = 3,
    target_n: int | None = None,
    difficulty: str | None = None,
    heartbeat_callback: Callable[[], None] | None = None,
    max_retries: int = 2,
) -> tuple[list[dict], list[float], int, int, str | None]:
    """
    Chunk text, retrieve relevant context chunks, generate once, then batch-validate.
    difficulty: EASY | MEDIUM | HARD (normalized to easy/medium/hard for LLM).
    Returns (mcqs, quality_scores, total_input_tokens, total_output_tokens, None).
    """
    t0 = time.perf_counter()
    target_n = target_n if target_n is not None else num_questions
    mode = getattr(settings, "chunk_mode", "semantic")
    chunks = chunk_text(
        full_text,
        mode=mode,
        chunk_size=getattr(settings, "chunk_size", 1500),
        overlap_fraction=getattr(settings, "chunk_overlap_fraction", 0.2),
    )
    if not chunks:
        logger.warning("generate_mcqs_with_rag: no chunks produced")
        return [], [], 0, 0, None

    logger.info("generate_mcqs_with_rag: chunks=%s num_questions=%s target_n=%s", len(chunks), num_questions, target_n)
    chunk_list = chunks
    outline_prefix = (global_outline or "").strip()
    if outline_prefix:
        outline_prefix = "Document outline:\n" + outline_prefix + "\n\n"
    _export_enabled = getattr(settings, "enable_export", False)
    if _export_enabled:
        logger.info("generate_mcqs_with_rag: baseline logging enabled; chunks=%s outline_len=%s", len(chunk_list), len(outline_prefix))

    _normalized_difficulty = (difficulty or "medium").strip().upper()
    if _normalized_difficulty not in ("EASY", "MEDIUM", "HARD"):
        _normalized_difficulty = "MEDIUM"
    _normalized_difficulty = _normalized_difficulty.lower()
    llm = get_llm_service()
    all_mcqs: list[dict] = []
    total_inp, total_out = 0, 0
    max_context_chunks = int(getattr(settings, "max_context_chunks", MAX_CONTEXT_CHUNKS) or MAX_CONTEXT_CHUNKS)
    if len(chunk_list) <= max_context_chunks:
        relevant_chunks = chunk_list
        logger.info("generate_mcqs_with_rag: small-doc path, using all chunks=%s", len(relevant_chunks))
    else:
        # Always use relevance retrieval for large docs to avoid all-chunk iteration for small target_n.
        # `use_rag` only controls upstream global-outline flow in tasks.py.
        logger.info("generate_mcqs_with_rag: loading embedding model")
        model = _embedding_model()
        logger.info("generate_mcqs_with_rag: embedding model ready=%s", model is not None)
        logger.info("generate_mcqs_with_rag: retrieving relevant chunks")
        relevant_chunks = retrieve_relevant_chunks(chunk_list, num_questions, topic_slugs)
        logger.info("generate_mcqs_with_rag: retrieved %d chunks", len(relevant_chunks))
        logger.info(
            "generate_mcqs_with_rag: retrieval path chunks=%s selected=%s use_rag=%s",
            len(chunk_list),
            len(relevant_chunks),
            use_rag,
        )

    combined_context = outline_prefix + "\n\n".join([_chunk_to_text(c) for c in relevant_chunks])
    attempts_used = 0
    for attempt in range(max_retries + 1):
        attempts_used = attempt + 1
        try:
            logger.info("generate_mcqs_with_rag: calling LLM generate")
            mcqs, inp, out = llm.generate_mcqs(
                combined_context,
                topic_slugs=topic_slugs,
                num_questions=num_questions,
                difficulty=_normalized_difficulty,
            )
            logger.info("generate_mcqs_with_rag: LLM returned %d candidates", len(mcqs))
        except Exception as e:
            logger.warning("LLM single-generation call failed (attempt=%s): %s", attempts_used, e)
            mcqs, inp, out = [], 0, 0
        total_inp += inp
        total_out += out
        all_mcqs = mcqs
        if heartbeat_callback:
            try:
                heartbeat_callback()
            except Exception:
                pass
        if all_mcqs:
            break
        if attempt < max_retries:
            logger.warning(
                "generate_mcqs_with_rag: zero MCQs on attempt %s/%s; retrying",
                attempt + 1,
                max_retries + 1,
            )
    logger.info(
        "generate_mcqs_with_rag: generation attempts_used=%s mcqs=%s",
        attempts_used,
        len(all_mcqs),
    )

    # Batch validation with automatic sequential fallback.
    scores: list[float] = []
    t_val = time.perf_counter()
    val_results, vi, vo = _validate_candidates(llm, all_mcqs, heartbeat_callback=heartbeat_callback)
    total_inp += vi
    total_out += vo
    for i, m in enumerate(all_mcqs):
        r = val_results[i] if i < len(val_results) else {}
        critique = str(r.get("critique", "") or "")
        m["validation_result"] = critique
        try:
            score = float(r.get("quality_score", quality_score_from_critique(critique)))
        except (TypeError, ValueError):
            score = quality_score_from_critique(critique)
        score = max(0.0, min(1.0, score))
        if bool(r.get("is_valid", True)) is False:
            score = min(score, 0.3)
        scores.append(score)
    for i, m in enumerate(all_mcqs):
        if i < len(scores):
            m["quality_score"] = scores[i]
    logger.info("generate_mcqs_with_rag: validation loop %.2fs", time.perf_counter() - t_val)

    elapsed_total = time.perf_counter() - t0
    logger.info("generate_mcqs_with_rag: total %.2fs mcqs=%s", elapsed_total, len(all_mcqs))
    return all_mcqs, scores, total_inp, total_out, None

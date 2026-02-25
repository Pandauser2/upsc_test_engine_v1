"""
MCQ generation service with RAG: sentence_transformers embeddings, FAISS vector store,
top-k retrieval per prompt. Clean synchronous parallel: 4 candidates via
ThreadPoolExecutor(max_workers=4), Sonnet only; no Message Batches.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import numpy as np

# Fixed 4 parallel candidates for sync Sonnet-only path (progress: X/4)
PARALLEL_CANDIDATES = 4

# FAISS index type (optional import); use type alias for clarity
FaissIndex: type = Any

from app.config import settings
from app.llm import get_llm_service
from app.services.chunking_service import chunk_text

logger = logging.getLogger(__name__)

# Quality: critique strings that indicate low quality
LOW_QUALITY_PHRASES = ("incorrect key", "wrong answer", "incorrect answer", "key is wrong", "explanation is wrong")


def _embedding_model():
    """Lazy-load sentence-transformers model."""
    if not hasattr(_embedding_model, "_model"):
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model._model = SentenceTransformer(
                getattr(settings, "rag_embedding_model", "all-MiniLM-L6-v2")
            )
        except Exception as e:
            logger.warning("sentence_transformers not available: %s", e)
            _embedding_model._model = None
    return _embedding_model._model


def build_faiss_index(chunks: list[str]) -> tuple[FaissIndex | None, list[str]]:
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
    index: FaissIndex | None,
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


def _partition_chunks(chunk_list: list[str], n: int) -> list[list[str]]:
    """Split chunk_list into n contiguous groups (for n parallel candidates)."""
    if not chunk_list or n <= 0:
        return [[]] * n if n else []
    size = len(chunk_list)
    if n >= size:
        return [[c] for c in chunk_list] + [[] for _ in range(n - size)]
    per = size // n
    remainder = size % n
    groups: list[list[str]] = []
    start = 0
    for i in range(n):
        take = per + (1 if i < remainder else 0)
        groups.append(chunk_list[start : start + take])
        start += take
    return groups


def generate_mcqs_with_rag(
    full_text: str,
    topic_slugs: list[str],
    num_questions: int,
    *,
    global_outline: str | None = None,
    use_rag: bool = True,
    target_n: int | None = None,
    difficulty: str | None = None,
    heartbeat_callback: Callable[[], None] | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[list[dict], list[float], int, int, str | None]:
    """
    Chunk text, then run exactly 4 parallel single Claude calls (one per candidate group).
    progress_callback(processed_count) called after each of 4 candidates completes (1–4).
    difficulty: EASY | MEDIUM | HARD (normalized to easy/medium/hard for LLM).
    Returns (mcqs, quality_scores, total_input_tokens, total_output_tokens, None).
    """
    t0 = time.perf_counter()
    target_n = target_n if target_n is not None else num_questions
    candidate_count = PARALLEL_CANDIDATES
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

    logger.info("generate_mcqs_with_rag: chunks=%s num_questions=%s target_n=%s candidates=%s", len(chunks), num_questions, target_n, candidate_count)
    t_index = time.perf_counter()
    index, chunk_list = build_faiss_index(chunks) if use_rag else (None, chunks)
    if use_rag:
        logger.info("generate_mcqs_with_rag: index build %.2fs", time.perf_counter() - t_index)
    top_k = getattr(settings, "rag_top_k", 5)
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
    groups = _partition_chunks(chunk_list, candidate_count)
    n_per_candidate = max(1, (num_questions + candidate_count - 1) // candidate_count)

    def _one_candidate(idx: int, chunk_group: list[str]) -> tuple[list[dict], int, int]:
        if not chunk_group:
            return [], 0, 0
        if use_rag and index is not None and len(chunk_group) == 1:
            query = chunk_group[0][:500]
            retrieved = retrieve_top_k(query, index, chunk_list, k=top_k)
            chunk_group = retrieved if retrieved else chunk_group
        combined = outline_prefix + "\n\n".join(chunk_group)
        if _export_enabled:
            logger.info("generate_mcqs_with_rag: candidate %s context_len=%s", idx, len(combined))
        try:
            return llm.generate_mcqs(combined, topic_slugs=topic_slugs, num_questions=n_per_candidate, difficulty=_normalized_difficulty)
        except Exception as e:
            logger.warning("LLM candidate %s failed: %s", idx, e)
            return [], 0, 0

    all_mcqs: list[dict] = []
    total_inp, total_out = 0, 0
    t_parallel = time.perf_counter()
    with ThreadPoolExecutor(max_workers=candidate_count) as executor:
        futures = {executor.submit(_one_candidate, i, groups[i]): i for i in range(candidate_count)}
        processed = 0
        for fut in as_completed(futures):
            try:
                mcqs, inp, out = fut.result()
                total_inp += inp
                total_out += out
                all_mcqs.extend(mcqs)
                processed += 1
                if progress_callback:
                    try:
                        progress_callback(processed)
                    except Exception:
                        logger.debug("progress_callback failed", exc_info=True)
                if heartbeat_callback:
                    try:
                        heartbeat_callback()
                    except Exception:
                        logger.debug("heartbeat_callback failed", exc_info=True)
            except Exception as e:
                logger.warning("Parallel candidate future failed: %s", e)
                processed += 1
                if progress_callback:
                    try:
                        progress_callback(processed)
                    except Exception:
                        logger.debug("progress_callback failed after future error", exc_info=True)
    elapsed_parallel = time.perf_counter() - t_parallel
    logger.info("generate_mcqs_with_rag: parallel block %.2fs (candidates=%s) mcqs=%s", elapsed_parallel, candidate_count, len(all_mcqs))

    # Self-validation and quality scoring (sequential to preserve order; can parallelize later)
    scores: list[float] = []
    t_val = time.perf_counter()
    for m in all_mcqs:
        try:
            critique, ci, co = llm.validate_mcq(m)
            total_inp += ci
            total_out += co
            m["validation_result"] = critique
            scores.append(quality_score_from_critique(critique))
        except Exception as e:
            logger.debug("validate_mcq failed: %s", e)
            m["validation_result"] = ""
            scores.append(0.5)
    for i, m in enumerate(all_mcqs):
        if i < len(scores):
            m["quality_score"] = scores[i]
    logger.info("generate_mcqs_with_rag: validation loop %.2fs", time.perf_counter() - t_val)

    elapsed_total = time.perf_counter() - t0
    logger.info("generate_mcqs_with_rag: total %.2fs mcqs=%s", elapsed_total, len(all_mcqs))
    return all_mcqs, scores, total_inp, total_out, None

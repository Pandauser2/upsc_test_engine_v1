"""
MCQ generation service with RAG: sentence_transformers embeddings, FAISS vector store,
top-k retrieval per prompt, batched LLM calls, self-validation with quality scoring.
"""
import logging
from typing import Any

import numpy as np

from app.config import settings
from app.llm import get_llm_service
from app.services.chunking_service import chunk_text
from app.services.summarization_service import generate_global_outline, summarize_chunk

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
) -> list[str]:
    """Retrieve top-k chunks by similarity to query. If index is None, return all chunks."""
    k = k or getattr(settings, "rag_top_k", 5)
    if index is None or not chunk_list:
        return chunk_list[: k * 2] if chunk_list else []

    model = _embedding_model()
    if model is None:
        return chunk_list[:k]

    try:
        import faiss
        q = model.encode([query])
        q = np.array(q, dtype=np.float32)
        distances, indices = index.search(q, min(k, len(chunk_list)))
        out = []
        for i in indices[0]:
            if 0 <= i < len(chunk_list):
                out.append(chunk_list[i])
        return out
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


def generate_mcqs_with_rag(
    full_text: str,
    topic_slugs: list[str],
    num_questions: int,
    *,
    global_outline: str | None = None,
    use_rag: bool = True,
    batch_size: int = 3,
) -> tuple[list[dict], list[float], int, int]:
    """
    Chunk text, optionally build RAG index, retrieve top-k per batch, call LLM in batches.
    Returns (mcqs, quality_scores, total_input_tokens, total_output_tokens).
    Each MCQ dict includes validation_result and optional quality_score.
    """
    mode = getattr(settings, "chunk_mode", "semantic")
    chunks = chunk_text(
        full_text,
        mode=mode,
        chunk_size=getattr(settings, "chunk_size", 1500),
        overlap_fraction=getattr(settings, "chunk_overlap_fraction", 0.2),
    )
    if not chunks:
        return [], [], 0, 0

    index, chunk_list = build_faiss_index(chunks) if use_rag else (None, chunks)
    top_k = getattr(settings, "rag_top_k", 5)

    # Build context: global outline + retrieved chunks per batch
    outline_prefix = (global_outline or "").strip()
    if outline_prefix:
        outline_prefix = "Document outline:\n" + outline_prefix + "\n\n"

    llm = get_llm_service()
    all_mcqs: list[dict] = []
    total_inp, total_out = 0, 0

    # Batch: take up to batch_size chunks per LLM call
    for start in range(0, len(chunk_list), batch_size):
        batch_chunks = chunk_list[start : start + batch_size]
        if use_rag and index is not None and len(batch_chunks) == 1:
            query = batch_chunks[0][:500]
            batch_chunks = retrieve_top_k(query, index, chunk_list, k=top_k)
        combined = outline_prefix + "\n\n".join(batch_chunks)
        n_per_batch = max(1, num_questions // max(1, (len(chunk_list) + batch_size - 1) // batch_size))
        try:
            mcqs, inp, out = llm.generate_mcqs(
                combined,
                topic_slugs=topic_slugs,
                num_questions=n_per_batch,
            )
            total_inp += inp
            total_out += out
            all_mcqs.extend(mcqs)
        except Exception as e:
            logger.warning("LLM batch failed: %s", e)

    # Self-validation and quality scoring
    scores: list[float] = []
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

    return all_mcqs, scores, total_inp, total_out

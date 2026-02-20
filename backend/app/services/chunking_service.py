"""
Chunking service: semantic (spaCy sentences + overlap) or fixed-size.
Config param for mode: fixed | semantic.
"""
import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

ChunkMode = Literal["fixed", "semantic"]

# Defaults
DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 0.2  # 20% overlap for semantic
DEFAULT_FIXED_OVERLAP_CHARS = 200


def _get_sentences_spacy(text: str) -> list[str]:
    """Split text into sentences using spaCy. Falls back to simple regex if spaCy unavailable."""
    try:
        import spacy
        nlp = getattr(_get_sentences_spacy, "_nlp", None)
        if nlp is None:
            try:
                nlp = spacy.load("en_core_web_sm")
            except OSError:
                nlp = spacy.load("en_core_web_sm", disable=["ner"])
            _get_sentences_spacy._nlp = nlp
        doc = nlp(text[:1_000_000])
        return [s.text.strip() for s in doc.sents if s.text.strip()]
    except Exception as e:
        logger.debug("spaCy sentence split failed, using regex: %s", e)
    # Fallback: split on sentence-ending punctuation
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_semantic(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_fraction: float = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """
    Semantic chunking: split by sentences (spaCy), build chunks of ~chunk_size chars with overlap_fraction overlap.
    overlap_fraction is the fraction of chunk_size to overlap (e.g. 0.2 = 20% overlap).
    """
    if not text or not text.strip():
        return []
    sentences = _get_sentences_spacy(text)
    if not sentences:
        return [text] if text.strip() else []

    overlap_chars = int(chunk_size * overlap_fraction)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent) + 1
        if current_len + sent_len > chunk_size and current:
            chunk_text = " ".join(current)
            chunks.append(chunk_text)
            # Overlap: keep trailing sentences that fit in overlap_chars
            overlap_len = 0
            keep: list[str] = []
            for s in reversed(current):
                if overlap_len + len(s) + 1 <= overlap_chars:
                    keep.append(s)
                    overlap_len += len(s) + 1
                else:
                    break
            current = list(reversed(keep))
            current_len = sum(len(s) + 1 for s in current)
        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_fixed(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_chars: int = DEFAULT_FIXED_OVERLAP_CHARS,
) -> list[str]:
    """Fixed-size chunking with character overlap."""
    if not text or not text.strip():
        return []
    text = text.strip()
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap_chars
        if start >= len(text):
            break
    return chunks


def chunk_text(
    text: str,
    mode: ChunkMode = "semantic",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap_fraction: float = DEFAULT_CHUNK_OVERLAP,
    overlap_chars: int = DEFAULT_FIXED_OVERLAP_CHARS,
) -> list[str]:
    """
    Chunk text by mode: 'semantic' (spaCy sentences + overlap) or 'fixed' (fixed-size + overlap).
    """
    if mode == "semantic":
        return chunk_semantic(text, chunk_size=chunk_size, overlap_fraction=overlap_fraction)
    return chunk_fixed(text, chunk_size=chunk_size, overlap_chars=overlap_chars)

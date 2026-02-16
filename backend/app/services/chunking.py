"""
Fixed-size chunking of extracted text for MCQ generation.
Chunk size by character count (MVP); pipeline collects MCQs until >= 50 then takes best 50.
"""
from typing import Iterator

# Target ~2500 chars per chunk so we get a few MCQs per chunk without overflowing context.
CHUNK_CHARS = 2500
OVERLAP_CHARS = 200


def chunk_text(text: str, chunk_size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """
    Split text into overlapping fixed-size chunks. Yields non-empty strings.
    """
    if not text or not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
        if start >= len(text):
            break
    return chunks

"""Unit tests for chunking service: fixed and semantic mode."""
import pytest

from app.services.chunking_service import (
    chunk_fixed,
    chunk_semantic,
    chunk_text,
)


def test_chunk_fixed_empty():
    assert chunk_fixed("") == []
    assert chunk_fixed("   ") == []


def test_chunk_fixed_single():
    text = "short"
    assert chunk_fixed(text, chunk_size=100) == ["short"]


def test_chunk_fixed_multiple():
    text = "a" * 500 + "b" * 500 + "c" * 500
    chunks = chunk_fixed(text, chunk_size=400, overlap_chars=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 450 for c in chunks)


def test_chunk_semantic_empty():
    assert chunk_semantic("") == []
    assert chunk_semantic("   ") == []


def test_chunk_semantic_single_sentence():
    text = "One sentence only."
    out = chunk_semantic(text, chunk_size=1000)
    assert len(out) == 1
    assert "sentence" in out[0]


def test_chunk_text_mode_fixed():
    text = "x" * 2000
    out = chunk_text(text, mode="fixed", chunk_size=500, overlap_chars=50)
    assert len(out) >= 2


def test_chunk_text_mode_semantic():
    text = "First sentence. Second sentence. Third sentence."
    out = chunk_text(text, mode="semantic", chunk_size=1000)
    assert len(out) >= 1
    assert "sentence" in " ".join(out)

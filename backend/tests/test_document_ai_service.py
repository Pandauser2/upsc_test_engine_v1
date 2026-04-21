"""Tests for Document AI page-chunking behavior."""

import pytest

from app.services import document_ai_service as mod


def _make_pdf_bytes(pages: int) -> bytes:
    try:
        import pymupdf
    except ImportError:
        pytest.skip("pymupdf not installed")
    with pymupdf.open() as doc:
        for i in range(pages):
            p = doc.new_page()
            p.insert_text((50, 50), f"Page {i + 1}")
        return doc.tobytes()


def test_process_pdf_bytes_single_call_when_under_limit(monkeypatch):
    pdf_bytes = _make_pdf_bytes(10)
    calls = {"n": 0}

    def fake_call(_bytes: bytes) -> str:
        calls["n"] += 1
        return "ok"

    monkeypatch.setattr(mod, "_call_document_ai", fake_call)
    out = mod.process_pdf_bytes(pdf_bytes)
    assert out == "ok"
    assert calls["n"] == 1


def test_process_pdf_bytes_chunks_when_over_limit(monkeypatch):
    pdf_bytes = _make_pdf_bytes(30)
    chunks = []

    def fake_call(chunk_bytes: bytes) -> str:
        try:
            import pymupdf
        except ImportError:
            pytest.skip("pymupdf not installed")
        with pymupdf.open(stream=chunk_bytes, filetype="pdf") as d:
            chunks.append(len(d))
            return f"chunk-{len(d)}"

    monkeypatch.setattr(mod, "_call_document_ai", fake_call)
    out = mod.process_pdf_bytes(pdf_bytes)
    assert chunks == [14, 14, 2]
    assert out == "chunk-14\nchunk-14\nchunk-2"


def test_process_pdf_bytes_exactly_14_pages_single_call(monkeypatch):
    pdf_bytes = _make_pdf_bytes(14)
    calls = {"n": 0}

    def fake_call(_bytes: bytes) -> str:
        calls["n"] += 1
        return "single-chunk-output"

    monkeypatch.setattr(mod, "_call_document_ai", fake_call)
    out = mod.process_pdf_bytes(pdf_bytes)
    assert calls["n"] == 1
    assert out == "single-chunk-output"


def test_process_pdf_bytes_exactly_15_pages_two_calls(monkeypatch):
    pdf_bytes = _make_pdf_bytes(15)
    chunk_page_counts = []

    def fake_call(chunk_bytes: bytes) -> str:
        try:
            import pymupdf
        except ImportError:
            pytest.skip("pymupdf not installed")
        with pymupdf.open(stream=chunk_bytes, filetype="pdf") as d:
            n = len(d)
            chunk_page_counts.append(n)
            return f"chunk-{n}"

    monkeypatch.setattr(mod, "_call_document_ai", fake_call)
    out = mod.process_pdf_bytes(pdf_bytes)
    assert len(chunk_page_counts) == 2
    assert chunk_page_counts == [14, 1]
    assert out == "chunk-14\nchunk-1"


def test_process_pdf_bytes_malformed_pdf_raises():
    with pytest.raises(Exception):
        mod.process_pdf_bytes(b"not a pdf")

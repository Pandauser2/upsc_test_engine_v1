"""Unit tests for RAG-first MCQ generation and batch validation behavior."""
from unittest.mock import Mock

from app.services import mcq_generation_service as svc


def _mk_mcq(i: int) -> dict:
    return {
        "question": f"Question {i} with enough text?",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "correct_option": "A",
        "explanation": "Because.",
        "difficulty": "medium",
        "topic_tag": "polity",
    }


def test_api_call_count_single_generation_and_batch_validation(monkeypatch):
    chunks = [f"chunk-{i}" for i in range(164)]
    llm = Mock()
    llm.generate_mcqs.return_value = ([_mk_mcq(i) for i in range(5)], 10, 20)
    llm.validate_mcqs_batch.return_value = (
        [{"is_valid": True, "quality_score": 0.8, "critique": "ok"} for _ in range(5)],
        5,
        6,
    )

    monkeypatch.setattr(svc, "chunk_text", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(svc, "get_llm_service", lambda: llm)
    monkeypatch.setattr(svc.settings, "max_context_chunks", 15)
    monkeypatch.setattr(svc.settings, "batch_validation_max", 20)

    mcqs, scores, *_ = svc.generate_mcqs_with_rag(
        full_text="irrelevant",
        topic_slugs=["polity"],
        num_questions=5,
    )
    assert len(mcqs) == 5
    assert len(scores) == 5
    assert llm.generate_mcqs.call_count == 1
    assert llm.validate_mcqs_batch.call_count == 1


def test_large_doc_still_uses_retrieval_when_use_rag_false(monkeypatch):
    chunks = [f"chunk-{i}" for i in range(164)]
    llm = Mock()
    llm.generate_mcqs.return_value = ([_mk_mcq(i) for i in range(3)], 10, 20)
    llm.validate_mcqs_batch.return_value = (
        [{"is_valid": True, "quality_score": 0.8, "critique": "ok"} for _ in range(3)],
        5,
        6,
    )
    retrieve = Mock(return_value=chunks[:15])

    monkeypatch.setattr(svc, "chunk_text", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(svc, "get_llm_service", lambda: llm)
    monkeypatch.setattr(svc, "retrieve_relevant_chunks", retrieve)
    monkeypatch.setattr(svc.settings, "max_context_chunks", 15)

    svc.generate_mcqs_with_rag(
        full_text="irrelevant",
        topic_slugs=["polity"],
        num_questions=5,
        use_rag=False,
    )

    assert retrieve.call_count == 1


def test_retrieve_relevant_chunks_caps_result(monkeypatch):
    chunks = [f"chunk-{i}" for i in range(164)]
    monkeypatch.setattr(svc.settings, "max_context_chunks", 15)
    out = svc.retrieve_relevant_chunks(chunks, num_questions=5, topic_tags=["history"])
    assert len(out) <= 15


def test_retrieve_relevant_chunks_fallback_spread_without_embeddings(monkeypatch):
    chunks = [{"index": i, "text": f"chunk-{i}"} for i in range(164)]
    monkeypatch.setattr(svc, "_embedding_model", lambda: None)
    monkeypatch.setattr(svc.settings, "max_context_chunks", 15)
    out = svc.retrieve_relevant_chunks(chunks, num_questions=5, topic_tags=["economy"])
    assert len(out) <= 15
    assert out
    first_idx = out[0]["index"]
    last_idx = out[-1]["index"]
    assert (last_idx - first_idx) >= int(0.5 * len(chunks))


def test_batch_validation_fallback_to_sequential(monkeypatch):
    candidates = [_mk_mcq(i) for i in range(5)]
    llm = Mock()
    llm.validate_mcqs_batch.side_effect = RuntimeError("batch failed")
    llm.validate_mcq.return_value = ("ok", 1, 1)
    monkeypatch.setattr(svc.settings, "batch_validation_max", 20)

    results, *_ = svc._validate_candidates(llm, candidates)
    assert len(results) == 5
    assert llm.validate_mcq.call_count == 5


def test_retry_guard_stops_after_max_retries(monkeypatch):
    llm = Mock()
    llm.generate_mcqs.return_value = ([], 0, 0)
    llm.validate_mcqs_batch.return_value = ([], 0, 0)
    monkeypatch.setattr(svc, "chunk_text", lambda *args, **kwargs: [f"chunk-{i}" for i in range(164)])
    monkeypatch.setattr(svc, "get_llm_service", lambda: llm)
    monkeypatch.setattr(svc, "retrieve_relevant_chunks", lambda chunks, num_questions, topic_tags: chunks[:15])

    out, *_ = svc.generate_mcqs_with_rag(
        full_text="irrelevant",
        topic_slugs=["polity"],
        num_questions=5,
        max_retries=2,
    )
    assert out == []
    assert llm.generate_mcqs.call_count <= 3

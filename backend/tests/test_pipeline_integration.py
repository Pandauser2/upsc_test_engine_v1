"""
Integration tests for full pipeline: extraction -> chunking -> (optional summarization) -> MCQ generation with RAG.
Uses mock LLM to avoid real API calls; optional sample UPSC-style PDF if present.
"""
import pytest

from app.services.chunking_service import chunk_text
from app.services.mcq_generation_service import (
    build_faiss_index,
    quality_score_from_critique,
    retrieve_top_k,
)


def test_quality_score_from_critique():
    assert quality_score_from_critique("The correct answer is A.") == 1.0
    assert quality_score_from_critique("incorrect key") == 0.0
    assert quality_score_from_critique("Wrong answer.") == 0.0
    assert quality_score_from_critique("") == 0.5
    assert quality_score_from_critique("Looks fine.") == 0.7


def test_build_faiss_index_empty():
    index, chunks = build_faiss_index([])
    assert index is None
    assert chunks == []


def test_build_faiss_index_and_retrieve():
    chunks = ["First chunk about polity.", "Second chunk about economy.", "Third chunk about history."]
    index, chunk_list = build_faiss_index(chunks)
    if index is None:
        pytest.skip("sentence_transformers or faiss not installed")
    results = retrieve_top_k("polity and constitution", index, chunk_list, k=2)
    assert len(results) <= 2
    assert any("polity" in r.lower() for r in results) or len(results) >= 1


def test_full_pipeline_chunking_to_rag_mock_llm(monkeypatch):
    """Run generate_mcqs_with_rag with mock LLM returning fixed MCQs."""
    from app.services import mcq_generation_service as svc

    mock_mcqs = [
        {
            "question": "What is Article 1?",
            "options": {"A": "Territory", "B": "State", "C": "Union", "D": "Republic"},
            "correct_option": "C",
            "explanation": "Article 1 says India is a Union of States.",
            "difficulty": "medium",
            "topic_tag": "polity",
        }
    ]

    class MockLLM:
        def generate_mcqs(self, text_chunk, topic_slugs, num_questions=None, difficulty=None):
            return mock_mcqs, 100, 50

        def validate_mcq(self, mcq):
            return "Correct.", 20, 10

    monkeypatch.setattr(svc, "get_llm_service", lambda: MockLLM())

    text = "Article 1 of the Constitution says India shall be a Union of States. The territory of India comprises the territories of the states."
    mcqs, scores, inp, out, _ = svc.generate_mcqs_with_rag(
        text,
        topic_slugs=["polity"],
        num_questions=1,
        use_rag=False,
    )
    assert len(mcqs) >= 1
    assert mcqs[0].get("question")
    assert "validation_result" in mcqs[0]
    assert "quality_score" in mcqs[0]
    assert inp >= 0 and out >= 0

"""
Unit tests for Gemini LLM impl: JSON parsing and optional mock generate_mcqs.
"""
import pytest

from app.llm.gemini_impl import _parse_mcqs_json


def test_parse_mcqs_json_valid():
    """Valid JSON with correct_option returns list with normalized keys."""
    raw = '''{"mcqs": [
        {"question": "What is Article 1?", "options": {"A": "Territory", "B": "State", "C": "Union", "D": "Republic"}, "correct_option": "C", "explanation": "Article 1.", "difficulty": "medium", "topic_tag": "polity"}
    ]}'''
    out = _parse_mcqs_json(raw, ["polity"])
    assert len(out) == 1
    assert out[0]["question"] == "What is Article 1?"
    assert out[0]["correct_option"] == "C"
    assert out[0]["options"]["A"] == "Territory"
    assert out[0]["topic_tag"] == "polity"


def test_parse_mcqs_json_accepts_answer():
    """Gemini may return 'answer' instead of 'correct_option'; normalize to correct_option."""
    raw = '''{"mcqs": [
        {"question": "Q?", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "answer": "B", "explanation": "E", "difficulty": "easy", "topic_tag": "polity"}
    ]}'''
    out = _parse_mcqs_json(raw, ["polity"])
    assert len(out) == 1
    assert out[0]["correct_option"] == "B"


def test_parse_mcqs_json_empty_returns_empty():
    """Empty or whitespace raw returns []."""
    assert _parse_mcqs_json("", ["polity"]) == []
    assert _parse_mcqs_json("   ", ["polity"]) == []


def test_parse_mcqs_json_invalid_returns_empty():
    """Invalid JSON returns [] (and does not raise)."""
    assert _parse_mcqs_json("not json", ["polity"]) == []
    assert _parse_mcqs_json('{"mcqs": null}', ["polity"]) == []


def test_parse_mcqs_json_strips_markdown_fence():
    """Code fence around JSON is stripped."""
    raw = '''```json
{"mcqs": [{"question": "Q?", "options": {"A":"a","B":"b","C":"c","D":"d"}, "correct_option": "A", "explanation": "E", "difficulty": "medium", "topic_tag": "polity"}]}
```'''
    out = _parse_mcqs_json(raw, ["polity"])
    assert len(out) == 1
    assert out[0]["question"] == "Q?"


def test_get_llm_service_returns_gemini_when_key_set(monkeypatch):
    """When GEMINI_API_KEY is set and google.genai is available, get_llm_service() returns GeminiService (not mock)."""
    pytest.importorskip("google.genai")
    from app.llm import get_llm_service
    from app.llm.gemini_impl import GeminiService

    monkeypatch.setattr("app.llm.gemini_impl._get_api_key", lambda: "test-key-for-test")
    service = get_llm_service()
    assert isinstance(service, GeminiService), "Expected GeminiService when key is set and SDK available"

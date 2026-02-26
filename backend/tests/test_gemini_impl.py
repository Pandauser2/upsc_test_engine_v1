"""
Unit tests for Gemini LLM impl: JSON parsing, model resolution, and optional mock generate_mcqs.
"""
import pytest

from app.llm.gemini_impl import _parse_mcqs_json, _resolve_model_name


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


def test_parse_mcqs_json_options_as_list():
    """Options as list of strings are normalized to A/B/C/D dict."""
    raw = '''{"mcqs": [{"question": "Q?", "options": ["First", "Second", "Third", "Fourth"], "correct_option": "B", "explanation": "E", "difficulty": "medium", "topic_tag": "polity"}]}'''
    out = _parse_mcqs_json(raw, ["polity"])
    assert len(out) == 1
    assert out[0]["options"]["A"] == "First"
    assert out[0]["options"]["B"] == "Second"
    assert out[0]["correct_option"] == "B"


def test_parse_mcqs_json_strips_leading_trailing_text():
    """Leading/trailing non-JSON text is stripped via first { to last }."""
    raw = '''Here is the JSON:\n{"mcqs": [{"question": "Q?", "options": {"A":"a","B":"b","C":"c","D":"d"}, "correct_option": "A", "explanation": "E", "difficulty": "medium", "topic_tag": "polity"}]}\nEnd.'''
    out = _parse_mcqs_json(raw, ["polity"])
    assert len(out) == 1
    assert out[0]["question"] == "Q?"


def test_resolve_model_name_unsupported_mapped_to_fallback():
    """Unsupported model ids (e.g. from old .env) are mapped to gemini-2.5-flash to avoid 404."""
    assert _resolve_model_name("gemini-1.5-flash-002") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-flash-001") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-flash") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-flash-003") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-pro") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-pro-001") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-2.0-flash") == "gemini-2.5-flash"


def test_resolve_model_name_supported_unchanged():
    """Supported model id (gemini-2.5-flash) is left unchanged; 2.0-flash and 1.5-pro mapped to fallback."""
    assert _resolve_model_name("gemini-2.5-flash") == "gemini-2.5-flash"
    assert _resolve_model_name("gemini-1.5-pro") == "gemini-2.5-flash"


def test_resolve_model_name_empty_returns_fallback():
    """Empty or whitespace returns fallback."""
    assert _resolve_model_name("") == "gemini-2.5-flash"
    assert _resolve_model_name("   ") == "gemini-2.5-flash"


def test_get_llm_service_returns_gemini_when_key_set(monkeypatch):
    """When GEMINI_API_KEY is set and google.genai is available, get_llm_service() returns GeminiService (not mock)."""
    pytest.importorskip("google.genai")
    from app.llm import get_llm_service
    from app.llm.gemini_impl import GeminiService

    monkeypatch.setattr("app.llm.gemini_impl._get_api_key", lambda: "test-key-for-test")
    service = get_llm_service()
    assert isinstance(service, GeminiService), "Expected GeminiService when key is set and SDK available"


def test_get_llm_service_uses_resolved_model_when_env_has_unsupported(monkeypatch):
    """When settings.gen_model_name is gemini-1.5-flash-002 (e.g. from .env), service uses gemini-2.0-flash."""
    pytest.importorskip("google.genai")
    from app.llm import get_llm_service
    from app.llm.gemini_impl import GeminiService
    import app.llm.gemini_impl as gemini_impl

    monkeypatch.setattr(gemini_impl, "_get_api_key", lambda: "test-key")
    fake_settings = type("Settings", (), {"gen_model_name": "gemini-1.5-flash-002"})()
    monkeypatch.setattr(gemini_impl, "settings", fake_settings)
    service = get_llm_service()
    assert isinstance(service, GeminiService)
    assert service._model_name == "gemini-2.5-flash"

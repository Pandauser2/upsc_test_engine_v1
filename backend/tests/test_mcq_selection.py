"""Tests for MCQ critique gating, quality-score fallback, and minimal-shape filtering."""
import pytest

from app.services.mcq_generation_service import (
    CRITIQUE_DROP_SUBSTRINGS,
    _mcq_minimal_shape,
    select_mcqs_for_persistence,
)


def _sample_mcq(i: int, critique: str, score: float | None = None) -> dict:
    m = {
        "question": f"Question {i} about the text with enough length?",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "correct_option": "A",
        "explanation": "Because.",
        "difficulty": "medium",
        "topic_tag": "polity",
        "validation_result": critique,
    }
    if score is not None:
        m["quality_score"] = score
    return m


def test_minimal_shape_rejects_short_question():
    m = _sample_mcq(1, "ok")
    m["question"] = "short"
    assert _mcq_minimal_shape(m) is False


def test_minimal_shape_rejects_missing_option():
    m = _sample_mcq(1, "ok")
    del m["options"]["D"]
    assert _mcq_minimal_shape(m) is False


def test_strict_mode_keeps_clean_critique():
    raw = [
        _sample_mcq(1, "The keyed answer is consistent and correct."),
        _sample_mcq(2, "Acceptable MCQ."),
    ]
    out, mode = select_mcqs_for_persistence(raw, target_n=5)
    assert mode == "strict"
    assert len(out) == 2


def test_strict_mode_drops_bad_key_phrase():
    raw = [
        _sample_mcq(1, "incorrect key: option B should be marked correct."),
        _sample_mcq(2, "Looks fine."),
    ]
    out, mode = select_mcqs_for_persistence(raw, target_n=5)
    assert mode == "strict"
    assert len(out) == 1
    assert "Looks fine" in (out[0].get("validation_result") or "")


def test_distractor_language_wrong_answer_does_not_drop_all():
    """Validator often says 'wrong answers' for distractors — must not zero the run."""
    raw = [
        _sample_mcq(1, "Option A is correct; B, C, D are wrong answers (distractors)."),
        _sample_mcq(2, "The incorrect answer choices are plausible."),
    ]
    out, mode = select_mcqs_for_persistence(raw, target_n=5)
    assert mode == "strict"
    assert len(out) == 2


def test_quality_fallback_when_every_critique_flags_key():
    raw = [
        _sample_mcq(1, "incorrect key", score=0.0),
        _sample_mcq(2, "key is wrong", score=0.0),
        _sample_mcq(3, "explanation is wrong", score=0.0),
    ]
    out, mode = select_mcqs_for_persistence(raw, target_n=2)
    assert mode == "quality_fallback"
    assert len(out) == 2
    # Sorted by quality (all 0) then medium-first order preserved among equals
    assert all(_mcq_minimal_shape(m) for m in out)


def test_quality_fallback_prefers_higher_score():
    raw = [
        _sample_mcq(1, "incorrect key", score=0.0),
        _sample_mcq(2, "key is wrong", score=0.0),
        _sample_mcq(3, "minor issue only", score=0.7),  # does not contain drop substrings
    ]
    # Third passes strict — should not need fallback
    out, mode = select_mcqs_for_persistence(raw, target_n=2)
    assert mode == "strict"
    assert len(out) == 1
    assert "minor issue" in (out[0].get("validation_result") or "").lower()


def test_empty_input():
    out, mode = select_mcqs_for_persistence([], target_n=5)
    assert mode == "empty"
    assert out == []


def test_custom_bad_substrings():
    raw = [_sample_mcq(1, "BANNED_PHRASE in critique")]
    out, mode = select_mcqs_for_persistence(raw, target_n=3, bad_substrings=("banned_phrase",))
    assert mode == "quality_fallback"
    assert len(out) == 1


def test_critique_drop_constants_not_overbroad():
    assert "wrong answer" not in " ".join(CRITIQUE_DROP_SUBSTRINGS).lower()

"""
Ranking (MVP): validation-score heuristic (no "incorrect key" in critique), prefer medium difficulty, optional topic diversity.
"""
from typing import Any


# Phrases that indicate the validation critique flagged a bad key (EXPLORATION §5).
INCORRECT_KEY_PHRASES = ("incorrect key", "wrong answer", "key is wrong", "correct answer is not", "key should be")


def _has_incorrect_key_flag(critique: str) -> bool:
    c = (critique or "").lower()
    return any(p in c for p in INCORRECT_KEY_PHRASES)


def rank_mcqs(
    mcqs: list[dict],
    validation_results: dict[int, str] | None = None,
    prefer_medium: bool = True,
    topic_diversity_weight: float = 0.0,
) -> list[dict]:
    """
    Rank MCQs: prefer no incorrect-key flag, then prefer medium difficulty, then optional topic spread.
    validation_results: index -> critique string (if already run).
    Returns new list in rank order (best first).
    """
    if not mcqs:
        return []
    validation_results = validation_results or {}

    def score(i: int, m: dict) -> tuple[float, str, int]:
        critique = validation_results.get(i, "")
        bad_key = 1.0 if _has_incorrect_key_flag(critique) else 0.0
        diff = m.get("difficulty", "").lower()
        medium_bonus = 0.5 if prefer_medium and diff == "medium" else 0.0
        # Primary: demote incorrect key; secondary: prefer medium
        return (-bad_key, -medium_bonus, i)

    indexed = list(enumerate(mcqs))
    indexed.sort(key=lambda x: score(x[0], x[1]))
    return [m for _, m in indexed]


def select_top_with_topic_diversity(mcqs: list[dict], n: int = 50) -> list[dict]:
    """
    Select top n MCQs favouring topic spread: round-robin by topic when possible.
    Simplified: take first n from already-ranked list; optional future: bucket by topic_tag and interleave.
    """
    return mcqs[:n]

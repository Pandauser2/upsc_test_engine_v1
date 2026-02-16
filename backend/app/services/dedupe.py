"""
Deduplication (MVP): Jaccard on stem word sets, stem word overlap, same correct + overlapping options.
No embeddings; keep one representative per cluster.
"""
import re
from typing import Callable


def _tokenize(s: str) -> set[str]:
    """Lowercase word tokens (no stemming for MVP)."""
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def stem_overlap_ratio(a: set[str], b: set[str]) -> float:
    """Overlap ratio: |intersection| / min(|a|,|b|)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def are_duplicate_mcqs(m1: dict, m2: dict, jaccard_threshold: float = 0.45, overlap_threshold: float = 0.5) -> bool:
    """
    True if two MCQs are likely duplicates: similar stems and/or same fact.
    Same correct_option + high option overlap also flags.
    """
    q1 = _tokenize(m1.get("question", ""))
    q2 = _tokenize(m2.get("question", ""))
    if jaccard(q1, q2) >= jaccard_threshold:
        return True
    if stem_overlap_ratio(q1, q2) >= overlap_threshold:
        return True
    if m1.get("correct_option") == m2.get("correct_option"):
        opts1 = _tokenize(" ".join(str(v) for v in (m1.get("options") or {}).values()))
        opts2 = _tokenize(" ".join(str(v) for v in (m2.get("options") or {}).values()))
        if jaccard(opts1, opts2) >= 0.4:
            return True
    return False


def deduplicate_mcqs(mcqs: list[dict], duplicate_fn: Callable[[dict, dict], bool] | None = None) -> list[dict]:
    """
    Keep first of each duplicate cluster; order preserved.
    """
    if duplicate_fn is None:
        duplicate_fn = are_duplicate_mcqs
    kept = []
    for m in mcqs:
        if any(duplicate_fn(m, k) for k in kept):
            continue
        kept.append(m)
    return kept

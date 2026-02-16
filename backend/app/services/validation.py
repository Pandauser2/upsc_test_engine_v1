"""
Self-validation pass: call LLM validate_mcq for each MCQ and attach critique to validation_result.
Used after selecting best 50 (or fewer) before persist. Returns token counts for cost tracking.
"""
from app.llm import get_llm_service


def run_validation_on_mcqs(mcqs: list[dict]) -> tuple[list[dict], int, int]:
    """
    For each MCQ, call validate_mcq and set validation_result on a copy.
    Returns (list of MCQs with validation_result, total_input_tokens, total_output_tokens).
    """
    service = get_llm_service()
    out = []
    ti, to = 0, 0
    for m in mcqs:
        critique, inp, out_tok = service.validate_mcq(m)
        ti += inp
        to += out_tok
        out.append({**m, "validation_result": critique})
    return out, ti, to

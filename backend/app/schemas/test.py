"""
Generated test and question schemas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, field_validator
from uuid import UUID


def _validate_options_dict(v: dict) -> dict:
    if not isinstance(v, dict):
        raise ValueError("options must be a dict")
    for k in ("A", "B", "C", "D"):
        if k not in v or not isinstance(v[k], str):
            raise ValueError("options must have A, B, C, D as string values")
    return v


def _validate_options_list(v: list) -> list:
    if not isinstance(v, list):
        raise ValueError("options must be a list")
    if len(v) not in (4, 5):
        raise ValueError("options must have 4 or 5 items")
    labels = ["A", "B", "C", "D", "E"]
    for i, o in enumerate(v):
        if not isinstance(o, dict):
            raise ValueError("each option must be {label, text}")
        lbl = (o.get("label") or "").strip().upper()
        if i < len(labels) and lbl != labels[i]:
            raise ValueError("options labels must be sequential A, B, C, D[, E]")
    return v


class QuestionPayload(BaseModel):
    question: str
    options: list | dict  # [{"label":"A","text":"..."}, ...] or legacy {"A":"...", ...}
    correct_option: str
    explanation: str
    difficulty: str
    topic_id: str  # UUID

    @field_validator("correct_option")
    @classmethod
    def correct_option_one_of(cls, v: str) -> str:
        if v not in ("A", "B", "C", "D", "E"):
            raise ValueError("correct_option must be A, B, C, D, or E")
        return v

    @field_validator("difficulty")
    @classmethod
    def difficulty_one_of(cls, v: str) -> str:
        if v not in ("easy", "medium", "hard"):
            raise ValueError("difficulty must be easy, medium, or hard")
        return v

    @field_validator("options")
    @classmethod
    def options_shape(cls, v: list | dict) -> list | dict:
        if isinstance(v, list):
            return _validate_options_list(v)
        return _validate_options_dict(v)

    class Config:
        from_attributes = True


class QuestionResponse(QuestionPayload):
    id: str
    generated_test_id: str
    sort_order: int
    validation_result: str | None = None

    class Config:
        from_attributes = True


class TestGenerateRequest(BaseModel):
    document_id: str
    num_questions: int = 15  # MVP: 1–20, default 15
    difficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"  # LLM must not decide
    export_result: bool = False  # When ENABLE_EXPORT=true, save MCQs to backend/exports/{test_id}.json

    @field_validator("num_questions")
    @classmethod
    def num_questions_range(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("num_questions must be between 1 and 20")
        return v


class TestResponse(BaseModel):
    id: str
    user_id: str
    document_id: str
    title: str | None
    status: str
    prompt_version: str
    model: str
    estimated_input_tokens: int | None
    estimated_output_tokens: int | None
    estimated_cost_usd: Decimal | None
    failure_reason: str | None = None  # set when status is failed
    created_at: datetime
    stale: bool = False  # True when status is pending/generating and older than max_generation_time (UI can show "may have timed out")
    # Progress when status is pending/generating (batch or parallel)
    questions_generated: int | None = None
    target_questions: int | None = None
    progress: float | None = None  # 0.0–1.0 when generating
    progress_message: str | None = None  # e.g. "3 of 10 questions created"
    elapsed_time: int | None = None  # time from create to done (seconds), computed from updated_at - created_at when status is terminal

    class Config:
        from_attributes = True


class TestDetailResponse(TestResponse):
    questions: list[QuestionResponse]


class TestListResponse(BaseModel):
    items: list[TestResponse]
    total: int


class TestStatusResponse(BaseModel):
    """Progress for generating test (X of Y questions created)."""
    status: str
    progress: float  # questions_generated / target_n, 0.0–1.0
    message: str
    questions_generated: int = 0
    target_questions: int = 0
    elapsed_time: int | None = None  # time from create to done (seconds), computed from updated_at - created_at when status is terminal


class TestPatchRequest(BaseModel):
    title: str | None = None


class QuestionPatchRequest(BaseModel):
    question: str | None = None
    options: list | dict | None = None
    correct_option: str | None = None
    explanation: str | None = None
    difficulty: str | None = None
    topic_id: str | None = None

    @field_validator("correct_option")
    @classmethod
    def correct_option_one_of(cls, v: str | None) -> str | None:
        if v is not None and v not in ("A", "B", "C", "D", "E"):
            raise ValueError("correct_option must be A, B, C, D, or E")
        return v

    @field_validator("difficulty")
    @classmethod
    def difficulty_one_of(cls, v: str | None) -> str | None:
        if v is not None and v not in ("easy", "medium", "hard"):
            raise ValueError("difficulty must be easy, medium, or hard")
        return v

    @field_validator("options")
    @classmethod
    def options_shape(cls, v: list | dict | None) -> list | dict | None:
        if v is not None:
            if isinstance(v, list):
                _validate_options_list(v)
            else:
                _validate_options_dict(v)
        return v

"""
Generated test and question schemas.
"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, field_validator
from uuid import UUID


def _validate_options(v: dict) -> dict:
    if not isinstance(v, dict):
        raise ValueError("options must be a dict")
    for k in ("A", "B", "C", "D"):
        if k not in v or not isinstance(v[k], str):
            raise ValueError("options must have A, B, C, D as string values")
    return v


class QuestionPayload(BaseModel):
    question: str
    options: dict  # {"A": str, "B": str, "C": str, "D": str}
    correct_option: str
    explanation: str
    difficulty: str
    topic_id: str  # UUID

    @field_validator("correct_option")
    @classmethod
    def correct_option_one_of(cls, v: str) -> str:
        if v not in ("A", "B", "C", "D"):
            raise ValueError("correct_option must be A, B, C, or D")
        return v

    @field_validator("difficulty")
    @classmethod
    def difficulty_one_of(cls, v: str) -> str:
        if v not in ("easy", "medium", "hard"):
            raise ValueError("difficulty must be easy, medium, or hard")
        return v

    @field_validator("options")
    @classmethod
    def options_shape(cls, v: dict) -> dict:
        return _validate_options(v)

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
    created_at: datetime

    class Config:
        from_attributes = True


class TestDetailResponse(TestResponse):
    questions: list[QuestionResponse]


class TestListResponse(BaseModel):
    items: list[TestResponse]
    total: int


class TestPatchRequest(BaseModel):
    title: str | None = None


class QuestionPatchRequest(BaseModel):
    question: str | None = None
    options: dict | None = None
    correct_option: str | None = None
    explanation: str | None = None
    difficulty: str | None = None
    topic_id: str | None = None

    @field_validator("correct_option")
    @classmethod
    def correct_option_one_of(cls, v: str | None) -> str | None:
        if v is not None and v not in ("A", "B", "C", "D"):
            raise ValueError("correct_option must be A, B, C, or D")
        return v

    @field_validator("difficulty")
    @classmethod
    def difficulty_one_of(cls, v: str | None) -> str | None:
        if v is not None and v not in ("easy", "medium", "hard"):
            raise ValueError("difficulty must be easy, medium, or hard")
        return v

    @field_validator("options")
    @classmethod
    def options_shape(cls, v: dict | None) -> dict | None:
        if v is not None:
            _validate_options(v)
        return v

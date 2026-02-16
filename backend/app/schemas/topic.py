"""
Topic list response (for dropdown and LLM prompt).
"""
from pydantic import BaseModel


class TopicResponse(BaseModel):
    id: str
    slug: str
    name: str

    class Config:
        from_attributes = True


class TopicListResponse(BaseModel):
    items: list[TopicResponse]

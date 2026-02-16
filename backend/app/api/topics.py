"""
Topics API: GET /topics (fixed list for dropdown and LLM prompt).
No auth required for read-only topic list; optionally require auth if needed later.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.topic_list import TopicList
from app.schemas.topic import TopicResponse, TopicListResponse

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=TopicListResponse)
def list_topics(db: Session = Depends(get_db)):
    """List all topics (id, slug, name) for dropdown and LLM prompt."""
    topics = db.query(TopicList).order_by(TopicList.sort_order, TopicList.slug).all()
    return TopicListResponse(
        items=[TopicResponse(id=str(t.id), slug=t.slug, name=t.name) for t in topics]
    )

"""
Prompt helpers: inject exact topic slugs into MCQ-generation prompt.
Require model to output one of them verbatim to avoid FK errors (EXPLORATION §5).
"""
from sqlalchemy.orm import Session
from app.models.topic_list import TopicList


def get_topic_slugs_for_prompt(db: Session) -> list[str]:
    """Return ordered list of topic slugs from topic_list for injection into prompt."""
    rows = db.query(TopicList).order_by(TopicList.sort_order, TopicList.slug).all()
    return [r.slug for r in rows]


def format_topic_slug_instruction(slugs: list[str]) -> str:
    """Format the exact instruction for the model: topic_tag must be exactly one of ..."""
    return (
        "topic_tag must be exactly one of (output verbatim, no other value): "
        + ", ".join(slugs)
    )

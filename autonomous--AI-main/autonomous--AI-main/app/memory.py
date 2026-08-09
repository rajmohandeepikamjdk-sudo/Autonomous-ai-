"""
AgentMemory is the single object every agent talks to for "have we done this
before" questions. It hides whether the answer comes from SQLite (exact
structured facts) or ChromaDB (semantic similarity) behind one interface.
"""
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select

from app.database import session_scope
from app.models import Post, TopicHistory
from app.vectorstore import get_vector_memory


class AgentMemory:
    def __init__(self):
        self.vector = get_vector_memory()

    def recent_topics(self, days: int = 14) -> List[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with session_scope() as session:
            rows = session.execute(
                select(TopicHistory.topic).where(TopicHistory.created_at >= cutoff)
            ).scalars().all()
            return list(rows)

    def record_topic_considered(self, topic: str, score: float, published: bool) -> None:
        with session_scope() as session:
            session.add(TopicHistory(topic=topic, score=score, was_published=published))

    def is_topic_too_similar(self, topic: str, draft_text: str, threshold: float) -> bool:
        similarity = self.vector.most_similar_topic_score(topic, draft_text or topic)
        return similarity >= threshold

    def writer_context(self, topic: str) -> List[str]:
        """Short snippets of previously published posts near this topic, so
        the writer avoids repeating itself verbatim."""
        return self.vector.recent_context(topic)

    def remember_published(self, post_id: str, title: str, text: str, topic: str) -> None:
        self.vector.add_post(post_id, title, text, topic)

    def post_count(self) -> int:
        with session_scope() as session:
            return session.query(Post).count()

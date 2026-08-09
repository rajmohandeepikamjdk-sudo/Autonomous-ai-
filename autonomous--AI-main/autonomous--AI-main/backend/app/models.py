import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Post(Base):
    """A published piece of content — what GET /api/agent/feed serves."""
    __tablename__ = "posts"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    topic = Column(String, nullable=False, index=True)
    content_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)

    sources = relationship("SourceRecord", back_populates="post", cascade="all, delete-orphan")

    def to_feed_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "text": self.text,
            "rationale": self.rationale,
            "sources": [s.url for s in self.sources],
            "createdAt": self.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


class SourceRecord(Base):
    """A source citation attached to a post."""
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=_uuid)
    post_id = Column(String, ForeignKey("posts.id"), nullable=False)
    url = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    trust_score = Column(Float, default=0.5)
    validated = Column(Boolean, default=False)

    post = relationship("Post", back_populates="sources")


class GenerationHistory(Base):
    """Every attempt at generating content, including failed/rejected ones."""
    __tablename__ = "generation_history"

    id = Column(String, primary_key=True, default=_uuid)
    topic = Column(String, nullable=False)
    stage = Column(String, nullable=False)  # e.g. "draft", "revision_1", "rejected"
    outcome = Column(String, nullable=False)  # "success" | "rejected" | "error"
    detail = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class AgentLog(Base):
    """Structured audit trail of every agent action, for /api/agent/logs."""
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent = Column(String, nullable=False, index=True)
    level = Column(String, default="INFO")
    message = Column(Text, nullable=False)
    cycle_id = Column(String, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, index=True)


class TopicHistory(Base):
    """Every topic ever considered, ranked, or published — used for dedup/trend memory."""
    __tablename__ = "topic_history"

    id = Column(String, primary_key=True, default=_uuid)
    topic = Column(String, nullable=False, index=True)
    score = Column(Float, default=0.0)
    was_published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

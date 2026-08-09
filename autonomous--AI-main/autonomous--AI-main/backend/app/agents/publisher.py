"""
PublisherAgent is the final gate: it decides whether an approved draft is a
duplicate (via content hash) and, if not, commits it to SQLite and to
semantic memory (ChromaDB) so future cycles know about it.
"""
import hashlib
import re

from app.agents.base_agent import BaseAgent, DraftPost
from app.database import session_scope
from app.linkedin_client import publish_to_linkedin, LinkedInPublishError
from app.models import Post, SourceRecord, GenerationHistory, TopicHistory
from app.agents.source_validation import SourceValidationAgent


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _content_hash(title: str, body: str) -> str:
    return hashlib.sha256(_normalize(title + body).encode()).hexdigest()


class PublisherAgent(BaseAgent):
    name = "PublisherAgent"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validator = SourceValidationAgent(self.llm, self.memory)

    async def publish(self, draft: DraftPost, cycle_id: str) -> str | None:
        """Persists the draft and returns the new post's id, or None if it
        was rejected as a duplicate. Returns an id (not an ORM object) so
        callers never touch a detached SQLAlchemy instance after the session
        closes.
        """
        content_hash = _content_hash(draft.title, draft.body)

        with session_scope() as session:
            existing = session.query(Post).filter_by(content_hash=content_hash).first()
            if existing is not None:
                self.log(f"Duplicate detected (hash={content_hash[:8]}...), skipping publish", "WARNING", cycle_id)
                session.add(GenerationHistory(
                    topic=draft.topic, stage="publish", outcome="rejected",
                    detail="Duplicate content hash",
                ))
                return None

            post = Post(
                title=draft.title,
                text=draft.body,
                rationale=draft.rationale,
                topic=draft.topic,
                content_hash=content_hash,
            )
            for url in draft.sources:
                domain = self._validator.domain_of(url)
                post.sources.append(SourceRecord(
                    url=url, domain=domain,
                    trust_score=self._validator.trust_score(domain),
                    validated=True,
                ))
            session.add(post)
            session.add(GenerationHistory(topic=draft.topic, stage="publish", outcome="success", detail=post.title))
            session.add(TopicHistory(topic=draft.topic, score=1.0, was_published=True))
            session.flush()
            post_id, title, body, topic = post.id, post.title, post.text, post.topic

        # Semantic memory write happens outside the DB transaction (separate
        # store), after the SQLite commit succeeds, so we never mark
        # something "remembered" that failed to persist.
        try:
            self.memory.remember_published(post_id, title, body, topic)
        except Exception as exc:  # noqa: BLE001 - vector memory is best-effort
            self.log(f"Vector memory write failed (non-fatal): {exc}", "ERROR", cycle_id)

        self.log(f"Published post '{title}' (id={post_id})", cycle_id=cycle_id)

        # LinkedIn is best-effort, same as the vector memory write above: a
        # failure here must never undo the local publish or crash the cycle.
        try:
            await publish_to_linkedin(title, body, cycle_id)
        except LinkedInPublishError as exc:
            self.log(f"LinkedIn publish failed (non-fatal, post is still live locally): {exc}", "ERROR", cycle_id)

        return post_id

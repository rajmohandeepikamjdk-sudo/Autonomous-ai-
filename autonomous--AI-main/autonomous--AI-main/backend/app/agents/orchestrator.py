"""
Orchestrator.run_cycle() is the entire autonomous loop, called once per
scheduler tick. It owns pipeline-level control flow (aborts, revision
retries) while each agent owns its own local decision-making.
"""
import uuid

from app.agents.base_agent import PipelineContext
from app.agents.topic_discovery import TopicDiscoveryAgent
from app.agents.source_validation import SourceValidationAgent
from app.agents.web_research import WebResearchAgent
from app.agents.content_writer import ContentWriterAgent
from app.agents.quality_reviewer import QualityReviewerAgent
from app.agents.fact_checker import FactCheckerAgent
from app.agents.publisher import PublisherAgent
from app.config import get_settings
from app.database import session_scope
from app.llm.base import LLMProvider
from app.logging_config import log_event
from app.memory import AgentMemory
from app.models import GenerationHistory

settings = get_settings()


class Orchestrator:
    def __init__(self, llm: LLMProvider):
        self.memory = AgentMemory()
        self.topic_agent = TopicDiscoveryAgent(llm, self.memory)
        self.source_agent = SourceValidationAgent(llm, self.memory)
        self.research_agent = WebResearchAgent(llm, self.memory)
        self.writer_agent = ContentWriterAgent(llm, self.memory)
        self.reviewer_agent = QualityReviewerAgent(llm, self.memory)
        self.fact_checker = FactCheckerAgent(llm, self.memory)
        self.publisher_agent = PublisherAgent(llm, self.memory)

        # Stats surfaced via GET /api/agent/status
        self.cycles_completed = 0
        self.cycles_failed = 0
        self.last_error: str | None = None

    async def run_cycle(self) -> dict:
        cycle_id = str(uuid.uuid4())[:8]
        log_event("Orchestrator", "Cycle started", cycle_id=cycle_id)
        ctx = PipelineContext(cycle_id=cycle_id)

        try:
            # 1-3: Topic Discovery -> Trend Analysis -> Topic Ranking
            ctx.topic, ctx.topic_score = await self.topic_agent.pick_topic(cycle_id)

            # 4: Source Validation (validate a candidate source pool for this topic)
            ctx.raw_sources = settings.research_source_list
            ctx.validated_sources = await self.source_agent.validate(ctx.raw_sources, cycle_id)
            if not ctx.validated_sources:
                ctx.aborted = True
                ctx.abort_reason = "No validated sources available"
                log_event("Orchestrator", ctx.abort_reason, "WARNING", cycle_id)
                self._record_generation(ctx.topic or "unknown", "abort", "rejected", ctx.abort_reason)
                self.cycles_completed += 1
                return self._summary(ctx)

            # 5: Research
            ctx.research_notes = await self.research_agent.research(ctx.topic, ctx.validated_sources, cycle_id)
            if not ctx.research_notes:
                ctx.aborted = True
                ctx.abort_reason = "No usable research notes gathered"
                log_event("Orchestrator", ctx.abort_reason, "WARNING", cycle_id)
                self._record_generation(ctx.topic, "abort", "rejected", ctx.abort_reason)
                self.cycles_completed += 1
                return self._summary(ctx)

            # 6-9: Reasoning + Content Generation -> Quality Review -> Fact Check,
            # with bounded revision retries.
            revision_feedback = None
            published_id = None
            for attempt in range(settings.MAX_CONTENT_REVISIONS + 1):
                ctx.revision_count = attempt
                ctx.draft = await self.writer_agent.write(
                    ctx.topic, ctx.research_notes, cycle_id, revision_feedback=revision_feedback
                )

                review = await self.reviewer_agent.review(ctx.draft, cycle_id)
                if not review.approved:
                    revision_feedback = review.reason
                    self._record_generation(ctx.topic, f"review_attempt_{attempt}", "rejected", review.reason)
                    continue

                fact_check = await self.fact_checker.check(ctx.draft, ctx.research_notes, cycle_id)
                if not fact_check.approved:
                    revision_feedback = fact_check.reason
                    self._record_generation(ctx.topic, f"factcheck_attempt_{attempt}", "rejected", fact_check.reason)
                    continue

                # Coarse semantic-dedup check against the actual draft body,
                # not just the topic string (catches near-duplicate angles on
                # an otherwise "fresh" topic).
                if self.memory.is_topic_too_similar(
                    ctx.topic, ctx.draft.body, threshold=settings.TOPIC_SIMILARITY_DEDUP_THRESHOLD
                ):
                    revision_feedback = "Too semantically similar to a previously published post; take a different angle."
                    self._record_generation(ctx.topic, f"dedup_attempt_{attempt}", "rejected", revision_feedback)
                    continue

                # 10: Store / Publish
                published_id = await self.publisher_agent.publish(ctx.draft, cycle_id)
                break

            if published_id is None:
                ctx.aborted = True
                ctx.abort_reason = "Exhausted revision attempts without an approved, verified draft"
                log_event("Orchestrator", ctx.abort_reason, "WARNING", cycle_id)
            else:
                log_event("Orchestrator", f"Cycle complete, published {published_id}", cycle_id=cycle_id)

            self.cycles_completed += 1
            return self._summary(ctx, published_id)

        except Exception as exc:  # noqa: BLE001 - top-level safety net so the
            # scheduler NEVER dies because one cycle threw; it just logs and
            # waits for the next tick.
            self.cycles_failed += 1
            self.last_error = str(exc)
            log_event("Orchestrator", f"Cycle failed with error: {exc}", "ERROR", cycle_id)
            self._record_generation(ctx.topic or "unknown", "error", "error", str(exc))
            return self._summary(ctx, error=str(exc))

    def _record_generation(self, topic: str, stage: str, outcome: str, detail: str) -> None:
        with session_scope() as session:
            session.add(GenerationHistory(topic=topic, stage=stage, outcome=outcome, detail=detail))

    def _summary(self, ctx: PipelineContext, published_id: str | None = None, error: str | None = None) -> dict:
        return {
            "cycle_id": ctx.cycle_id,
            "topic": ctx.topic,
            "aborted": ctx.aborted,
            "abort_reason": ctx.abort_reason,
            "revision_count": ctx.revision_count,
            "published_id": published_id,
            "error": error,
        }

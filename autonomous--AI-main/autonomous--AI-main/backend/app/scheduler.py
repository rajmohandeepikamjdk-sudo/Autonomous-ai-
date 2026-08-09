"""
Owns the APScheduler instance and the single global AgentState. This is what
makes the system "autonomous after one request": once `start()` is called
from POST /api/agent/init, the scheduler keeps firing `run_cycle()` inside
the FastAPI process's event loop, with no further HTTP requests needed.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.agents.orchestrator import Orchestrator
from app.config import get_settings
from app.database import session_scope
from app.llm.providers import build_llm_provider
from app.logging_config import log_event
from app.models import Post

settings = get_settings()


class AgentState:
    """Process-wide singleton tracking whether the agent has been
    initialized, plus the stats served by GET /api/agent/status.
    """

    def __init__(self):
        self.initialized = False
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.orchestrator: Optional[Orchestrator] = None
        self.last_run_at: Optional[datetime] = None

    def is_running(self) -> bool:
        return bool(self.scheduler and self.scheduler.running)

    async def _job(self) -> None:
        assert self.orchestrator is not None
        result = await self.orchestrator.run_cycle()
        self.last_run_at = datetime.now(timezone.utc)
        log_event("Scheduler", f"Cycle result: {result}")

    def start(self) -> bool:
        """Idempotent: returns True if this call actually started the
        scheduler, False if it was already running (so /init is safe to call
        more than once, per the spec's "called exactly once" contract — we
        still defend against accidental double-calls).
        """
        if self.initialized and self.is_running():
            return False

        self.orchestrator = Orchestrator(build_llm_provider())
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(
            self._job,
            trigger=IntervalTrigger(minutes=settings.PIPELINE_INTERVAL_MINUTES),
            id="content_pipeline_cycle",
            next_run_time=datetime.now(timezone.utc),  # fire once immediately, then on interval
            max_instances=1,  # never let two cycles overlap
            coalesce=True,
        )
        self.scheduler.start()
        self.initialized = True
        log_event(
            "Scheduler",
            f"Started. Interval={settings.PIPELINE_INTERVAL_MINUTES}min, "
            f"llm_provider={settings.LLM_PROVIDER}, research_mode={settings.RESEARCH_MODE}",
        )
        return True

    def status(self) -> dict:
        next_run = None
        if self.scheduler and self.scheduler.get_job("content_pipeline_cycle"):
            job = self.scheduler.get_job("content_pipeline_cycle")
            next_run = job.next_run_time.isoformat() if job.next_run_time else None

        with session_scope() as session:
            total_posts = session.query(Post).count()

        return {
            "initialized": self.initialized,
            "scheduler_running": self.is_running(),
            "cycles_completed": self.orchestrator.cycles_completed if self.orchestrator else 0,
            "cycles_failed": self.orchestrator.cycles_failed if self.orchestrator else 0,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": next_run,
            "last_error": self.orchestrator.last_error if self.orchestrator else None,
            "total_posts": total_posts,
        }


agent_state = AgentState()

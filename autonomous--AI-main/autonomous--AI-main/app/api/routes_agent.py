from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from app.config import get_settings
from app.database import session_scope
from app.models import Post, AgentLog
from app.scheduler import agent_state
from app.schemas import (
    InitResponse, FeedResponse, PostOut, StatusResponse, LogsResponse, LogEntryOut,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])
settings = get_settings()


@router.post("/init", response_model=InitResponse)
async def init_agent():
    """Initialize the system exactly once: loads config, starts the
    scheduler, and begins autonomous execution. Safe to call more than once
    (idempotent) — subsequent calls report that it's already running rather
    than spawning a second scheduler.
    """
    started = agent_state.start()
    return InitResponse(
        status="started" if started else "already_running",
        message=(
            "Agent initialized. Autonomous pipeline is now running in the background "
            f"every {settings.PIPELINE_INTERVAL_MINUTES} minutes."
            if started
            else "Agent was already initialized; scheduler continues running."
        ),
        scheduler_started=started,
        pipeline_interval_minutes=settings.PIPELINE_INTERVAL_MINUTES,
    )


@router.get("/feed", response_model=FeedResponse)
async def get_feed(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Reverse-chronological feed of published posts."""
    with session_scope() as session:
        posts = (
            session.query(Post)
            .order_by(desc(Post.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return FeedResponse(posts=[PostOut(**p.to_feed_dict()) for p in posts])


@router.get("/status", response_model=StatusResponse)
async def get_status():
    """Live monitoring endpoint: scheduler state, cycle counters, last error."""
    return StatusResponse(**agent_state.status())


@router.get("/logs", response_model=LogsResponse)
async def get_logs(limit: int = Query(100, ge=1, le=500), agent: str | None = None):
    """Structured audit trail of every agent action, most recent first."""
    with session_scope() as session:
        q = session.query(AgentLog).order_by(desc(AgentLog.created_at))
        if agent:
            q = q.filter(AgentLog.agent == agent)
        rows = q.limit(limit).all()
        return LogsResponse(logs=[
            LogEntryOut(
                agent=r.agent, level=r.level, message=r.message, cycle_id=r.cycle_id,
                createdAt=r.created_at.isoformat(),
            ) for r in rows
        ])


@router.get("/posts/{post_id}", response_model=PostOut)
async def get_post(post_id: str):
    with session_scope() as session:
        post = session.query(Post).filter_by(id=post_id).first()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        return PostOut(**post.to_feed_dict())

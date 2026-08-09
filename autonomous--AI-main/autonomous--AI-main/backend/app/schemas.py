from typing import List, Optional
from pydantic import BaseModel


class PostOut(BaseModel):
    id: str
    title: str
    text: str
    rationale: str
    sources: List[str]
    createdAt: str


class FeedResponse(BaseModel):
    posts: List[PostOut]


class InitResponse(BaseModel):
    status: str
    message: str
    scheduler_started: bool
    pipeline_interval_minutes: int


class StatusResponse(BaseModel):
    initialized: bool
    scheduler_running: bool
    cycles_completed: int
    cycles_failed: int
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_error: Optional[str] = None
    total_posts: int


class LogEntryOut(BaseModel):
    agent: str
    level: str
    message: str
    cycle_id: Optional[str] = None
    createdAt: str


class LogsResponse(BaseModel):
    logs: List[LogEntryOut]

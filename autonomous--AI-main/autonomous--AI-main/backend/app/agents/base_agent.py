from dataclasses import dataclass, field
from typing import List, Optional

from app.llm.base import LLMProvider
from app.logging_config import log_event
from app.memory import AgentMemory


@dataclass
class ResearchNote:
    source_url: str
    domain: str
    trust_score: float
    snippet: str


@dataclass
class DraftPost:
    title: str
    body: str
    rationale: str
    topic: str
    sources: List[str]


@dataclass
class AgentDecision:
    approved: bool
    reason: str


@dataclass
class PipelineContext:
    """The single object threaded through every pipeline stage. Each agent
    reads what it needs and appends its own output — this is the
    'communication protocol' between agents: typed fields, not free text.
    """
    cycle_id: str
    candidate_topics: List[str] = field(default_factory=list)
    topic: Optional[str] = None
    topic_score: float = 0.0
    raw_sources: List[str] = field(default_factory=list)
    validated_sources: List[str] = field(default_factory=list)
    research_notes: List[ResearchNote] = field(default_factory=list)
    draft: Optional[DraftPost] = None
    revision_count: int = 0
    aborted: bool = False
    abort_reason: str = ""


class BaseAgent:
    """Common plumbing: every agent gets a name (for logs), the shared LLM
    provider, and the shared memory facade.
    """

    name = "BaseAgent"

    def __init__(self, llm: LLMProvider, memory: AgentMemory):
        self.llm = llm
        self.memory = memory

    def log(self, message: str, level: str = "INFO", cycle_id: str | None = None) -> None:
        log_event(self.name, message, level=level, cycle_id=cycle_id)

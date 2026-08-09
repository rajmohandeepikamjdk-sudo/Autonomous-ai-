"""
Unit tests per agent, isolated from the network and from each other by using
MockLLM directly and an in-memory-equivalent SQLite test DB.
"""
import os
import tempfile

import pytest

_tmp_dir = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_dir}/unit_test_agent.db")
os.environ.setdefault("CHROMA_PERSIST_DIR", f"{_tmp_dir}/chroma_unit")
os.environ.setdefault("LLM_PROVIDER", "mock")

from app.database import init_db  # noqa: E402
from app.llm.providers import MockLLM  # noqa: E402
from app.memory import AgentMemory  # noqa: E402
from app.agents.base_agent import ResearchNote, DraftPost  # noqa: E402
from app.agents.topic_discovery import TopicDiscoveryAgent  # noqa: E402
from app.agents.source_validation import SourceValidationAgent  # noqa: E402
from app.agents.quality_reviewer import QualityReviewerAgent  # noqa: E402
from app.agents.fact_checker import FactCheckerAgent  # noqa: E402
from app.agents.publisher import PublisherAgent  # noqa: E402

init_db()


@pytest.fixture
def llm():
    return MockLLM()


@pytest.fixture
def memory():
    return AgentMemory()


@pytest.mark.asyncio
async def test_topic_discovery_picks_a_topic(llm, memory):
    agent = TopicDiscoveryAgent(llm, memory)
    topic, score = await agent.pick_topic(cycle_id="test1")
    assert isinstance(topic, str) and topic
    assert score >= 0


@pytest.mark.asyncio
async def test_source_validation_rejects_blocked_and_unknown_low_trust(llm, memory):
    agent = SourceValidationAgent(llm, memory)
    sources = ["https://arxiv.org/abs/1234", "https://clickbait.biz/x", "not-a-url"]
    validated = await agent.validate(sources, cycle_id="test2")
    assert "https://arxiv.org/abs/1234" in validated
    assert "https://clickbait.biz/x" not in validated
    assert "not-a-url" not in validated


@pytest.mark.asyncio
async def test_quality_reviewer_rejects_short_body(llm, memory):
    agent = QualityReviewerAgent(llm, memory)
    draft = DraftPost(title="X", body="too short", rationale="r", topic="t", sources=["https://arxiv.org"])
    decision = await agent.review(draft, cycle_id="test3")
    assert decision.approved is False


@pytest.mark.asyncio
async def test_fact_checker_fails_with_no_notes(llm, memory):
    agent = FactCheckerAgent(llm, memory)
    draft = DraftPost(title="X", body="word " * 60, rationale="r", topic="t", sources=[])
    decision = await agent.check(draft, notes=[], cycle_id="test4")
    assert decision.approved is False


@pytest.mark.asyncio
async def test_publisher_rejects_exact_duplicate(llm, memory):
    agent = PublisherAgent(llm, memory)
    draft = DraftPost(
        title="Same Title", body="Same body content here.", rationale="r",
        topic="dup-topic", sources=["https://arxiv.org/abs/9999"],
    )
    first_id = await agent.publish(draft, cycle_id="dup1")
    second_id = await agent.publish(draft, cycle_id="dup2")
    assert first_id is not None
    assert second_id is None  # rejected as duplicate

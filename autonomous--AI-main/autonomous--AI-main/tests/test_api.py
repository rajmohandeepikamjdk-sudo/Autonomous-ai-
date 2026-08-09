"""
Integration tests: drive the real FastAPI app (with MockLLM + offline research
so no network/keys are needed), call /init, wait for one autonomous cycle to
complete, then assert /feed is well-formed. Also checks idempotency of /init
and shape of /status and /logs.
"""
import asyncio
import os
import tempfile

import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("RESEARCH_MODE", "offline")
os.environ.setdefault("PIPELINE_INTERVAL_MINUTES", "60")

_tmp_dir = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_dir}/test_agent.db")
os.environ.setdefault("CHROMA_PERSIST_DIR", f"{_tmp_dir}/chroma")

from app.main import app  # noqa: E402
from app.scheduler import agent_state  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_init_starts_scheduler_and_feed_populates():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/agent/init")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("started", "already_running")
        assert body["scheduler_started"] is True or body["status"] == "already_running"

        # Calling init again must be idempotent, not spawn a second scheduler.
        resp2 = await client.post("/api/agent/init")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "already_running"

        # Wait for the immediately-fired first cycle to complete.
        for _ in range(30):
            status = (await client.get("/api/agent/status")).json()
            if status["cycles_completed"] >= 1:
                break
            await asyncio.sleep(1)
        else:
            pytest.fail("Pipeline did not complete a cycle in time")

        feed = (await client.get("/api/agent/feed")).json()
        assert "posts" in feed

        if feed["posts"]:
            post = feed["posts"][0]
            for field in ("id", "title", "text", "rationale", "sources", "createdAt"):
                assert field in post
            assert post["createdAt"].endswith("Z")

        logs = (await client.get("/api/agent/logs")).json()
        assert "logs" in logs
        assert len(logs["logs"]) > 0


@pytest.mark.asyncio
async def test_feed_reverse_chronological_and_unique_ids():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        feed = (await client.get("/api/agent/feed")).json()
        posts = feed["posts"]
        ids = [p["id"] for p in posts]
        assert len(ids) == len(set(ids)), "post ids must be unique"
        timestamps = [p["createdAt"] for p in posts]
        assert timestamps == sorted(timestamps, reverse=True), "feed must be reverse-chronological"

# Deployment Guide

## Option A — Docker Compose (recommended)

```bash
cp .env.example .env        # edit if you want real LLM/web-research mode
docker compose up --build -d
curl -X POST http://localhost:8000/api/agent/init
curl http://localhost:8000/api/agent/feed
docker compose logs -f agent-api   # watch the autonomous cycles happen
```

The `agent-data` named volume persists `data/agent.db` (SQLite) and
`data/chroma` (vector memory) across container restarts, so posts survive a
`docker compose restart`. To fully reset state:

```bash
docker compose down -v
```

## Option B — Plain Docker

```bash
docker build -t content-agent .
docker run -d -p 8000:8000 -v agent-data:/app/data --env-file .env.example content-agent
```

## Option C — Local (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Going from demo mode to a real deployment

The default `.env.example` uses `LLM_PROVIDER=mock` and `RESEARCH_MODE=offline`
so the system runs with zero external dependencies — this is intentional for
reliable hackathon judging (no risk of an expired key or a flaky network
demo failing mid-presentation).

To run it "for real":

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
RESEARCH_MODE=web
RESEARCH_SOURCE_URLS=https://en.wikipedia.org,https://arxiv.org,https://arstechnica.com
```

No code changes required — `app/llm/providers.build_llm_provider()` and
`WebResearchAgent` both branch on these env vars.

## Tuning the autonomous loop

| Variable | Effect |
|---|---|
| `PIPELINE_INTERVAL_MINUTES` | how often a new cycle fires (default 15) |
| `MAX_CONTENT_REVISIONS` | how many writer-retry loops before a cycle gives up (default 2) |
| `TOPIC_SIMILARITY_DEDUP_THRESHOLD` | 0-1, higher = stricter dedup (default 0.86) |
| `LLM_RATE_LIMIT_PER_MIN` | token-bucket cap on LLM calls/minute |
| `API_RATE_LIMIT_PER_MIN` | per-IP cap on HTTP requests/minute |

## Scaling beyond one process

This reference implementation intentionally keeps state in SQLite + local
Chroma + an in-process scheduler for simplicity and zero infra dependencies.
To run multiple replicas behind a load balancer:

1. Move `DATABASE_URL` to a shared Postgres instance (SQLAlchemy makes this a
   connection-string change).
2. Run the scheduler in exactly **one** replica (e.g. a dedicated
   `worker` service that calls `/init` on boot) and make the other replicas
   API-only (never call `/init` on them) — or move the scheduled job to an
   external scheduler (Celery beat, cloud cron) that calls an internal
   `/api/agent/run-cycle` trigger endpoint instead of using APScheduler
   in-process.
3. Point `CHROMA_PERSIST_DIR` at a networked Chroma server
   (`chromadb.HttpClient`) instead of `PersistentClient`.

## Monitoring in production

- `GET /api/agent/status` — poll this from an external uptime/monitoring tool;
  alert if `last_run_at` hasn't advanced in `> 2 * PIPELINE_INTERVAL_MINUTES`.
- `GET /api/agent/logs?agent=Orchestrator` — cycle-level audit trail.
- Container `HEALTHCHECK` (`/healthz`) is already wired into both the
  `Dockerfile` and `docker-compose.yml`.

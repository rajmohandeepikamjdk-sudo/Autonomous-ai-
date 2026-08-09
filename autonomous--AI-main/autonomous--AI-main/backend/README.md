# Autonomous AI Content Agent

A self-driving content pipeline: **one API call** (`POST /api/agent/init`) boots a
multi-agent system that keeps discovering topics, researching them, writing posts,
fact-checking itself, and publishing to a feed (`GET /api/agent/feed`) — forever,
on a schedule, with no further human prompting.

Built for a hackathon demo: it runs **out of the box with zero API keys** (a
deterministic `MockLLM` provider stands in for GPT/Claude/Llama), and becomes a
real LLM-backed system the moment you drop an API key into `.env`.

```
docker compose up --build
curl -X POST http://localhost:8000/api/agent/init
curl http://localhost:8000/api/agent/feed
```

Open http://localhost:8000/docs for interactive Swagger API docs.

---

## Going live (real internet + a real LLM)

Out of the box the pipeline is 100% offline — `MockLLM` writes deterministic
posts and the research stage invents plausible-sounding findings, so nothing
ever leaves your machine. That's what makes it safe to demo without keys.

To make it actually go online — fetch real pages and think with a real
model — edit the `.env` file at the project root (docker-compose loads it
automatically):

```bash
# .env  (Groq is free, no credit card — see console.groq.com)
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...             # paste your real key
RESEARCH_MODE=web                # was: offline
RESEARCH_SOURCE_URLS=https://en.wikipedia.org/wiki/Artificial_intelligence,https://arstechnica.com/ai/
```

Note: as of 2026, OpenAI and Anthropic no longer offer free API tiers — both
require billing set up before a key will generate anything. If you want a
genuinely free key with no credit card, use `LLM_PROVIDER=groq` (get a key at
console.groq.com) or wire in Google Gemini yourself, which is also free.
`LLM_PROVIDER=openai` / `anthropic` still work exactly as before if you do
have a paid key.

Then restart:

```bash
docker compose up --build
```

What changes under the hood:
- `WebResearchAgent` (`app/agents/web_research.py`) now `httpx.get()`s each
  URL in `RESEARCH_SOURCE_URLS` for real, strips it down to plain text, and
  asks the LLM to summarize only what's actually on the page — no more
  invented findings.
- `build_llm_provider()` (`app/llm/providers.py`) swaps `MockLLM` for the
  real provider you picked (`GroqProvider`, `OpenAIProvider`, or
  `AnthropicProvider`), so topic brainstorming, writing, review, and
  fact-checking all run on a real model. Groq is called through the `openai`
  package pointed at Groq's OpenAI-compatible endpoint, so no new dependency
  was needed.
- Everything else — the orchestrator, retries, dedup, the API, the landing
  page — is untouched, since every agent only depends on the `LLMProvider`
  interface, not a concrete provider.

If `LLM_PROVIDER` is set but the matching API key is blank, it silently
falls back to `MockLLM` rather than crashing on boot — so a typo in your key
degrades to demo mode instead of taking the service down. Check
`GET /api/agent/logs` if posts look templated even after adding a key; that
fallback is the first thing to rule out.

---

## 1. Why this satisfies "autonomous"

`POST /api/agent/init` is called **exactly once**. It:

1. Loads `Settings` from environment (`app/config.py`).
2. Initializes SQLite (`app/database.py`) and the vector memory store (`app/vectorstore.py`).
3. Instantiates the seven agents and wires them into an `Orchestrator` (`app/agents/orchestrator.py`).
4. Starts an `APScheduler` background job (`app/scheduler.py`) that runs the full
   pipeline every `PIPELINE_INTERVAL_MINUTES` (default 15 min, configurable), plus
   fires one run immediately.
5. Returns `202 Accepted` — the HTTP request completes, but the scheduler thread
   keeps running inside the FastAPI process, executing pipeline cycles
   indefinitely without any further requests.

Calling `/init` again is idempotent (returns current status, does not spawn a
second scheduler) — see `agent_state.py`.

## 2. Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full diagrams. Summary:

```
Scheduler (APScheduler)
   │  every N minutes, fire-and-forget async job
   ▼
Orchestrator.run_cycle()
   │
   ├─ TopicDiscoveryAgent   → candidate topics (seed list + memory-derived + LLM brainstorm)
   ├─ TrendAnalysis (in TopicDiscoveryAgent) → recency/frequency scored
   ├─ TopicRankingAgent     → scores & picks ONE topic not covered recently (dedup via vector memory)
   ├─ SourceValidationAgent → validates/filters candidate sources (domain allowlist, reachability)
   ├─ WebResearchAgent      → gathers findings per source (pluggable: web_search tool or offline stub)
   ├─ ContentWriterAgent    → LLM reasoning + draft (title, body, rationale)
   ├─ QualityReviewerAgent  → LLM self-critique, may request rewrite (bounded retries)
   ├─ FactCheckerAgent      → cross-checks claims against research notes, flags unsupported claims
   ├─ PublisherAgent        → dedup hash check → persist to SQLite → embed into ChromaDB memory
   ▼
SQLite (posts, sources, generation_history, agent_logs, topic_history)
   ▼
GET /api/agent/feed  (reverse-chronological JSON)
```

## 3. Agents — communication, memory, decisions, retries

| Agent | Input | Output | Decision it makes |
|---|---|---|---|
| TopicDiscoveryAgent | seed topics + recent topic_history | ranked candidate list | "which subjects are even in play this cycle" |
| SourceValidationAgent | raw source URLs/domains | filtered, scored sources | "which sources are trustworthy enough to cite" |
| WebResearchAgent | validated sources + topic | structured `ResearchNote[]` | "what evidence exists, and how strong is it" |
| ContentWriterAgent | research notes | draft `Post` + `rationale` | "what's the angle, what's worth saying" |
| QualityReviewerAgent | draft post | approve / revise / reject | "is this good enough to publish" |
| FactCheckerAgent | draft post + research notes | pass / fail + flagged claims | "is every claim traceable to a source" |
| PublisherAgent | approved post | persisted `Post` row | "is this a duplicate; commit or discard" |

**Communication.** Agents don't call each other directly — the `Orchestrator`
passes a shared `PipelineContext` (a typed dataclass) through each stage
sequentially, so every agent's output is the next agent's typed input. This
keeps agents independently testable and swappable (e.g., swap `WebResearchAgent`
for a Bing/SerpAPI-backed one without touching anything else).

**Memory.** Two tiers:
- *Structured memory* (SQLite): every post, source, topic, and log line — the
  system of record, queried by the API.
- *Semantic memory* (ChromaDB): embeddings of published post titles+text, used
  by `TopicRankingAgent` to avoid re-covering a topic it already wrote about
  (cosine-similarity dedup) and to give the writer "what have I said before"
  context so it doesn't contradict itself.

**Decision making.** Each agent exposes a single `decide()`/`run()` method that
returns a typed verdict (`AgentDecision`), not free text — e.g. the Reviewer
returns `{approved: bool, reason: str}`. The Orchestrator branches on that
verdict rather than parsing prose, which is what makes the retry logic
reliable.

**Retry logic.** `app/utils/retry.py` provides an async `retry_with_backoff`
decorator (exponential backoff + jitter, max attempts configurable) used on
every network/LLM call. On top of that, the Orchestrator has pipeline-level
retry semantics:
- If `FactCheckerAgent` fails a draft, the orchestrator sends it back to
  `ContentWriterAgent` with the failure reason appended to context, up to
  `MAX_CONTENT_REVISIONS` (default 2) times, then drops the cycle and logs it
  rather than publishing something unverified.
- If `WebResearchAgent` finds zero usable sources, the cycle aborts early
  (logged as `skipped_no_sources`) rather than hallucinating content.

## 4. Reliability features

- **Duplicate prevention**: SHA-256 hash of `normalized(title+text)` stored per
  post; `PublisherAgent` rejects exact/near duplicates. Topic-level dedup via
  vector similarity threshold in `TopicRankingAgent`.
- **Source verification**: `SourceValidationAgent` checks domain against an
  allow/deny list and (optionally) does a `HEAD`/`GET` reachability check.
- **Retry + backoff**: all outbound calls (LLM, HTTP) wrapped.
- **Structured logging**: every agent action is written to `agent_logs` (SQLite)
  and to stdout via Python `logging`, so `GET /api/agent/logs` gives a live
  audit trail for judges.
- **Rate limiting**: `app/utils/rate_limit.py` is a simple token-bucket used to
  throttle LLM calls per minute (`LLM_RATE_LIMIT_PER_MIN`), and FastAPI routes
  are protected by a lightweight per-IP limiter middleware.
- **Monitoring**: `GET /api/agent/status` reports scheduler state, last run
  time, next run time, cycle counts, and last error.

## 5. Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI + Uvicorn |
| LLM | Pluggable: OpenAI, Anthropic, Ollama(Llama), or built-in `MockLLM` |
| Vector DB | ChromaDB (local persistent client) |
| DB | SQLite via SQLAlchemy ORM |
| Scheduler | APScheduler (AsyncIOScheduler) |
| Deployment | Docker / docker-compose |
| Tests | pytest + httpx |

## 6. Project layout

```
autonomous-content-agent/
├── app/
│   ├── main.py              # FastAPI app, startup wiring
│   ├── config.py            # Settings (env-driven)
│   ├── database.py          # SQLAlchemy engine/session
│   ├── models.py            # ORM models (Post, Source, GenerationHistory, AgentLog, TopicHistory)
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── memory.py             # AgentMemory facade over SQLite + Chroma
│   ├── vectorstore.py        # ChromaDB wrapper
│   ├── scheduler.py          # APScheduler wiring + agent_state singleton
│   ├── logging_config.py     # logging setup + DB log sink
│   ├── llm/
│   │   ├── base.py           # LLMProvider protocol
│   │   └── providers.py      # OpenAI / Anthropic / Ollama / Mock implementations
│   ├── agents/
│   │   ├── base_agent.py
│   │   ├── topic_discovery.py
│   │   ├── web_research.py
│   │   ├── source_validation.py
│   │   ├── content_writer.py
│   │   ├── quality_reviewer.py
│   │   ├── fact_checker.py
│   │   ├── publisher.py
│   │   └── orchestrator.py
│   ├── api/
│   │   └── routes_agent.py   # /api/agent/* endpoints
│   └── utils/
│       ├── retry.py
│       └── rate_limit.py
├── tests/
│   ├── test_api.py
│   └── test_agents.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEPLOYMENT.md
│   └── TESTING.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## 7. Configuration (`.env`)

See `.env.example`. Nothing is required to run — defaults use `MockLLM` and a
built-in offline research stub so the whole loop works with no external
network access, which matters for a hackathon judging environment.

```
LLM_PROVIDER=mock            # mock | openai | anthropic | ollama
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
PIPELINE_INTERVAL_MINUTES=15
MAX_CONTENT_REVISIONS=2
LLM_RATE_LIMIT_PER_MIN=20
DATABASE_URL=sqlite:///./data/agent.db
CHROMA_PERSIST_DIR=./data/chroma
```

## 8. Running locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 9. Testing

```bash
pytest -v
```

See [`docs/TESTING.md`](docs/TESTING.md) for strategy (unit tests per agent with
mocked LLM/HTTP, integration test that drives `/init` → waits for one cycle →
asserts `/feed` is non-empty and well-formed).

## 10. Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

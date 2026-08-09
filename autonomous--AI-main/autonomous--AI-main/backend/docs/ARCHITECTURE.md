# Architecture

## 1. System context

```mermaid
flowchart LR
    Client[Client / Judge / curl] -->|POST /api/agent/init once| API
    Client -->|GET /api/agent/feed, /status, /logs| API

    subgraph FastAPI Process
        API[FastAPI Layer]
        API --> Sched[APScheduler\nAsyncIOScheduler]
        Sched -->|every N minutes\nfire-and-forget| Orch[Orchestrator]
        Orch --> Agents[Seven Agents]
        Agents --> LLM[LLM Provider\nOpenAI / Anthropic / Ollama / Mock]
        Agents --> HTTP[httpx\nweb research / reachability]
        Agents --> DB[(SQLite)]
        Agents --> Vec[(ChromaDB\nsemantic memory)]
    end

    API --> DB
```

`POST /api/agent/init` is the only request the system ever needs. It starts
the `AsyncIOScheduler` living inside the same asyncio event loop as the
FastAPI/uvicorn server, so background cycles keep firing for the lifetime of
the process — no cron, no external worker, no additional prompting.

## 2. Pipeline (the eight boxes from the spec, mapped to code)

```mermaid
flowchart TD
    A[Scheduler tick] --> B[TopicDiscoveryAgent\nDiscovery]
    B --> C[TopicDiscoveryAgent\nTrend Analysis]
    C --> D[TopicDiscoveryAgent\nTopic Ranking]
    D --> E[SourceValidationAgent\nSource Validation]
    E -->|no valid sources| Z1[Abort cycle, log, wait for next tick]
    E --> F[WebResearchAgent\nResearch]
    F -->|no usable notes| Z1
    F --> G[ContentWriterAgent\nReasoning + Content Generation]
    G --> H[QualityReviewerAgent\nQuality Review]
    H -->|REVISE, attempts left| G
    H -->|APPROVE| I[FactCheckerAgent\nFact Checking]
    I -->|FAIL, attempts left| G
    I -->|PASS| J{Semantic dedup check\nAgentMemory}
    J -->|too similar, attempts left| G
    J -->|OK| K[PublisherAgent\nStore]
    H -->|attempts exhausted| Z2[Abort cycle, log, wait for next tick]
    I -->|attempts exhausted| Z2
    J -->|attempts exhausted| Z2
    K --> L[(SQLite: posts, sources,\ngeneration_history, topic_history)]
    K --> M[(ChromaDB: post embeddings)]
    L --> N[GET /api/agent/feed]
```

Every "attempts left" branch is bounded by `MAX_CONTENT_REVISIONS` (default
2); once exhausted the cycle aborts cleanly and logs why, rather than
publishing something unverified or looping forever.

## 3. Agent communication

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant TD as TopicDiscoveryAgent
    participant SV as SourceValidationAgent
    participant WR as WebResearchAgent
    participant CW as ContentWriterAgent
    participant QR as QualityReviewerAgent
    participant FC as FactCheckerAgent
    participant PB as PublisherAgent

    O->>TD: pick_topic(cycle_id)
    TD-->>O: (topic, score)
    O->>SV: validate(raw_sources, cycle_id)
    SV-->>O: validated_sources[]
    O->>WR: research(topic, validated_sources, cycle_id)
    WR-->>O: ResearchNote[]
    loop up to MAX_CONTENT_REVISIONS+1
        O->>CW: write(topic, notes, feedback?)
        CW-->>O: DraftPost
        O->>QR: review(draft)
        QR-->>O: AgentDecision(approved, reason)
        O->>FC: check(draft, notes)
        FC-->>O: AgentDecision(approved, reason)
    end
    O->>PB: publish(draft, cycle_id)
    PB-->>O: post_id or None (duplicate)
```

Agents never call each other directly. The Orchestrator passes a single
typed `PipelineContext` dataclass through each stage — this is the entire
"communication protocol": typed fields in, typed fields/decisions out. It
keeps every agent independently unit-testable (see `tests/test_agents.py`)
and swappable — e.g. replacing `WebResearchAgent`'s offline stub with a real
search-API-backed implementation touches exactly one file.

## 4. Memory model

```mermaid
flowchart LR
    subgraph Structured Memory - SQLite
        Posts[(posts)]
        Sources[(sources)]
        GenHist[(generation_history)]
        TopicHist[(topic_history)]
        Logs[(agent_logs)]
    end

    subgraph Semantic Memory - ChromaDB
        Embeddings[(post embeddings\nhashing bag-of-words)]
    end

    PublisherAgent -->|on publish| Posts
    PublisherAgent -->|on publish| Sources
    PublisherAgent -->|on publish| Embeddings
    Orchestrator -->|every attempt| GenHist
    TopicDiscoveryAgent -->|every candidate| TopicHist
    AllAgents[Every Agent] -->|every action| Logs

    TopicDiscoveryAgent -->|dedup check| Embeddings
    ContentWriterAgent -->|"what have I said before?"| Embeddings
```

- **Structured memory (SQLite)** is the system of record: what the API
  serves, what a judge can inspect directly with any SQLite browser.
- **Semantic memory (ChromaDB)** uses a small dependency-free hashing
  embedding function (see `app/vectorstore.py`) instead of Chroma's default
  model, specifically so the whole system — including near-duplicate
  detection — runs with **zero network access and zero model downloads**.
  Swapping in a real sentence-transformer or an OpenAI embeddings call is a
  one-line change if embedding quality matters more than offline guarantees
  in your deployment.

## 5. Data model (SQLite)

```mermaid
erDiagram
    POSTS ||--o{ SOURCES : cites
    POSTS {
        string id PK
        string title
        text text
        text rationale
        string topic
        string content_hash UK
        datetime created_at
    }
    SOURCES {
        string id PK
        string post_id FK
        string url
        string domain
        float trust_score
        bool validated
    }
    GENERATION_HISTORY {
        string id PK
        string topic
        string stage
        string outcome
        text detail
        datetime created_at
    }
    TOPIC_HISTORY {
        string id PK
        string topic
        float score
        bool was_published
        datetime created_at
    }
    AGENT_LOGS {
        int id PK
        string agent
        string level
        text message
        string cycle_id
        datetime created_at
    }
```

## 6. Retry & failure semantics

| Failure | Handled by | Behavior |
|---|---|---|
| LLM call throws | `utils/retry.retryable` | exponential backoff + jitter, up to N attempts, then `RetryExhaustedError` bubbles to caller |
| HTTP fetch/HEAD throws | `utils/retry.retryable` | same, used in `SourceValidationAgent`/`WebResearchAgent` |
| Draft fails review | `Orchestrator.run_cycle` | feedback fed back into `ContentWriterAgent`, bounded by `MAX_CONTENT_REVISIONS` |
| Draft fails fact-check | `Orchestrator.run_cycle` | same bounded revision loop |
| Draft too similar to prior post | `Orchestrator.run_cycle` | same bounded revision loop |
| Revisions exhausted | `Orchestrator.run_cycle` | cycle aborts, logged, **nothing published**, scheduler waits for next tick |
| No validated sources / no research notes | `Orchestrator.run_cycle` | cycle aborts early, logged as `abort` |
| Any uncaught exception in a cycle | `Orchestrator.run_cycle` top-level try/except | logged to `agent_logs` + `generation_history`, `cycles_failed` incremented, **scheduler itself is never killed** |
| Duplicate content | `PublisherAgent` (SHA-256 content hash) | rejected, logged, cycle ends without publishing |
| Vector memory (Chroma) unavailable | `VectorMemory` | fails open — dedup checks return "not similar", writer context returns empty; pipeline still runs |

## 7. Why this design scales beyond a hackathon demo

- Swapping `LLM_PROVIDER` or `RESEARCH_MODE` is a config change, not a code
  change — every agent depends only on the `LLMProvider` interface.
- Each agent is a small, independently testable class with one job; adding
  an eighth agent (e.g. an `ImageGeneratorAgent` for post thumbnails) means
  adding one file and one line in `Orchestrator.__init__`.
- The Orchestrator's control flow (aborts, revisions, top-level exception
  guard) is the only place cross-cutting reliability logic lives, so it's
  auditable in one file (`app/agents/orchestrator.py`) instead of scattered
  across seven agents.

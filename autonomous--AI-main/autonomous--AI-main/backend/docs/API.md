# API Reference

Base URL (local): `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs` (Swagger) and `/redoc`.

All timestamps are ISO 8601 UTC, e.g. `2026-08-08T04:12:31.512000Z`.

---

## `POST /api/agent/init`

Initializes the system **exactly once** and begins autonomous execution.
Idempotent: a second call does not spawn a second scheduler.

**Request body:** none.

**Response `200`:**
```json
{
  "status": "started",
  "message": "Agent initialized. Autonomous pipeline is now running in the background every 15 minutes.",
  "scheduler_started": true,
  "pipeline_interval_minutes": 15
}
```

On a repeat call:
```json
{
  "status": "already_running",
  "message": "Agent was already initialized; scheduler continues running.",
  "scheduler_started": false,
  "pipeline_interval_minutes": 15
}
```

---

## `GET /api/agent/feed`

Returns published posts, **reverse chronological**.

**Query params:**
| param | default | description |
|---|---|---|
| `limit` | 50 | max posts to return (1-200) |
| `offset` | 0 | pagination offset |

**Response `200`:**
```json
{
  "posts": [
    {
      "id": "8f14e45f-ceea-4d5e-8b8d-1a2b3c4d5e6f",
      "title": "What's actually new in Progress in autonomous agent orchestration",
      "text": "Progress in autonomous agent orchestration has moved quickly...",
      "rationale": "Selected because 'Progress in autonomous agent orchestration' scored highest this cycle...",
      "sources": ["https://en.wikipedia.org", "https://arstechnica.com"],
      "createdAt": "2026-08-08T04:12:31.512000Z"
    }
  ]
}
```

Every post has a unique `id` (UUID4), and `sources` reflects the exact
citations validated and used for that post.

---

## `GET /api/agent/posts/{post_id}`

Fetch a single post by id. `404` if not found.

---

## `GET /api/agent/status`

Live monitoring: scheduler state and cycle counters.

**Response `200`:**
```json
{
  "initialized": true,
  "scheduler_running": true,
  "cycles_completed": 4,
  "cycles_failed": 0,
  "last_run_at": "2026-08-08T04:12:31.998000Z",
  "next_run_at": "2026-08-08T04:27:31.998000+00:00",
  "last_error": null,
  "total_posts": 3
}
```

Note `cycles_completed` includes cycles that aborted (no sources / no
verified draft) — those are counted as "ran" but not "published". Use
`total_posts` vs `cycles_completed` together to gauge the pipeline's publish
rate, and `GET /api/agent/logs` to see exactly why a given cycle didn't
publish.

---

## `GET /api/agent/logs`

Structured audit trail, most recent first.

**Query params:**
| param | default | description |
|---|---|---|
| `limit` | 100 | max entries (1-500) |
| `agent` | none | filter to one agent, e.g. `FactCheckerAgent` |

**Response `200`:**
```json
{
  "logs": [
    {
      "agent": "PublisherAgent",
      "level": "INFO",
      "message": "Published post 'What's actually new in ...' (id=8f14e45f-...)",
      "cycle_id": "a1b2c3d4",
      "createdAt": "2026-08-08T04:12:31.998000+00:00"
    }
  ]
}
```

`cycle_id` lets you filter/grep a single pipeline run end-to-end across every
agent's log lines.

---

## `GET /healthz`

Liveness probe for Docker/orchestrators. Returns `{"status": "ok"}`.

---

## Error responses

All errors follow FastAPI's standard shape:
```json
{ "detail": "human-readable message" }
```
| status | when |
|---|---|
| `404` | `GET /api/agent/posts/{id}` with an unknown id |
| `429` | per-IP rate limit exceeded (`API_RATE_LIMIT_PER_MIN`) |
| `500` | unhandled server error (logged server-side, never leaks a stack trace to the client) |

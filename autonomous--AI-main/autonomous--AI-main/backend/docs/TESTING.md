# Testing Strategy

```bash
pytest -v
```

## Layers

### 1. Unit tests — `tests/test_agents.py`

Each agent is tested in isolation using `MockLLM` (deterministic, offline)
and a throwaway SQLite/Chroma path per test run (via `tempfile.mkdtemp()`),
so tests never touch real developer data and never require network access
or API keys.

Covered:
- `TopicDiscoveryAgent` returns a non-empty topic with a valid score.
- `SourceValidationAgent` correctly accepts a trusted domain and rejects a
  blocklisted domain and a malformed URL.
- `QualityReviewerAgent` rejects a too-short draft via the cheap heuristic
  check (no LLM call needed — proves the fast-fail path works independent of
  the LLM).
- `FactCheckerAgent` fails closed when given zero research notes (proves the
  system never publishes ungrounded content even if research silently
  returns nothing).
- `PublisherAgent` publishes an identical draft once, then rejects the exact
  duplicate on a second call (proves the content-hash dedup works).

### 2. Integration tests — `tests/test_api.py`

Drives the real FastAPI app end-to-end over ASGI (no real network socket):
1. `POST /api/agent/init` → asserts `200` and a `started` status.
2. Calls `/init` again → asserts it reports `already_running` (idempotency).
3. Polls `GET /api/agent/status` until `cycles_completed >= 1`.
4. Asserts `GET /api/agent/feed` returns a well-formed list — every post has
   `id`, `title`, `text`, `rationale`, `sources`, `createdAt`, and the
   timestamp is UTC (`Z`-suffixed ISO 8601).
5. Asserts `GET /api/agent/logs` is non-empty (every agent logs at least
   once per cycle).
6. Separately asserts feed ordering is strictly reverse-chronological and
   every post id is unique.

### 3. Manual / demo checklist

- [ ] `docker compose up --build` from a clean checkout succeeds with no
      `.env` edits (proves the zero-key demo path works).
- [ ] `POST /api/agent/init` returns within ~1s (the actual pipeline cycle
      runs in the background, not inline in the request).
- [ ] Within one `PIPELINE_INTERVAL_MINUTES` window, `GET /api/agent/feed`
      has at least one post OR `GET /api/agent/logs` clearly explains why not
      (e.g. `abort: No validated sources available`).
- [ ] Calling `/init` a second time does not create duplicate posts or a
      second scheduler (`GET /api/agent/status` still reports one scheduler,
      `scheduler_running: true`).
- [ ] Killing and restarting the container preserves prior posts (volume
      persistence).

## What's intentionally NOT covered by automated tests

- Real LLM provider integrations (`OpenAIProvider`, `AnthropicProvider`,
  `OllamaProvider`) are thin, mechanically-verified-by-inspection wrappers
  around each SDK's documented call shape — testing them meaningfully would
  require live API keys and network access, which contradicts the
  reproducible/offline testing goal. `MockLLM` exercises the exact same
  `LLMProvider` interface every agent depends on, so agent logic itself is
  fully covered without needing real credentials.
- Load/concurrency testing of the scheduler running many overlapping cycles —
  `max_instances=1` on the APScheduler job guarantees cycles never overlap,
  which removes the concurrency hazard by construction rather than needing a
  stress test to catch it.

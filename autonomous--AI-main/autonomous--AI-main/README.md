# Autonomous AI Content Agent

An autonomous multi-agent system that researches, writes, fact-checks, and publishes content on its own — no human prompting after the first call.

🔗 **Live Demo:** https://autonomousaiagent.netlify.app
🔗 **Live API Docs:** https://autonomous-ai-364r.onrender.com/docs
🔗 **GitHub Repo:** https://github.com/hari12harans-byte/autonomous--AI

> Note: the backend runs on a free-tier server, so the first load can take 30–50 seconds to "wake up." Please wait a moment on first visit.

---

## How it works

Call `POST /api/agent/init` **once**. A scheduler wakes up and, without any further prompting, runs a 7-agent pipeline on a loop:

1. **Topic Discovery** — finds candidate topics
2. **Source Validation** — checks and scores research sources for trust
3. **Web Research** — pulls real content from live sources
4. **Content Writer** — drafts a post from the research
5. **Quality Review** — reviews the draft, requests revisions if weak
6. **Fact Checker** — rejects claims not backed by research notes
7. **Publisher** — publishes the approved, verified post to the feed

Results are exposed via `GET /api/agent/feed`, live logs via `GET /api/agent/logs`.

## Tech Stack

- **Backend:** FastAPI, SQLite, ChromaDB (vector memory), APScheduler, Docker
- **Frontend:** Vanilla HTML/CSS/JS dashboard (no framework, no build step)
- **LLM:** Pluggable provider support (Groq / OpenAI / Anthropic / Mock for offline demo)
- **Deployment:** Backend on Render, Frontend on Netlify

## Project Structure
autonomous-content-agent/
├── backend/ FastAPI app — agents, API, DB, scheduler, tests, Docker
└── frontend/ Standalone dashboard (index.html) + tiny static server
## Run it locally

**1. Backend** (in one terminal):
```bash
cd backend
docker compose up --build
# or, without Docker:
#   python -m venv venv && source venv/bin/activate
#   pip install -r requirements.txt
#   uvicorn app.main:app --reload
```
Runs at http://localhost:8000 (docs at `/docs`).

**2. Frontend** (in another terminal):
```bash
cd frontend
node server.js
```
Runs at http://localhost:3000. Open it, set "API Base" to `http://localhost:8000`, click **Connect**, then **Initialize agent**.

## Why two separate servers?

Originally FastAPI served `index.html` directly at `/`, so frontend and backend were one process. This split lets each run/deploy independently (frontend on Netlify, backend on Render). CORS is already open on the backend (`app/main.py`), and the dashboard has a built-in "API Base" field for pointing at a remote backend — so no application logic needed to change, just where each part lives.

See `backend/README.md` and `frontend/README.md` for more detail on each half.

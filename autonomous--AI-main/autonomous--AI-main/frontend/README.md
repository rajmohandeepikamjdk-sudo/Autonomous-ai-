# Frontend

This is the original `index.html` dashboard (unchanged) — a single self-contained
HTML/CSS/JS file, no build step, no npm dependencies. `server.js` is a tiny
zero-dependency static file server added so it can run on its own port,
separate from the backend.

## Run it

```bash
cd frontend
node server.js
```

Open **http://localhost:3000**.

(No Node? Any static server works: `python -m http.server 3000`, or
`npx serve -l 3000`.)

## Point it at the backend

The page has an **"API Base"** field at the top (blank = same origin).
Since the frontend now runs on a different port than the backend, set it to
wherever the backend is running, e.g.:

```
http://localhost:8000
```

then click **Connect**. The backend already has CORS wide open
(`allow_origins=["*"]` in `app/main.py`), so cross-port requests work
without any backend changes.

## Backend must be running first

```bash
cd ../backend
docker compose up --build
# or: uvicorn app.main:app --reload
```

Then in the frontend, hit **Connect** → **Init Agent** to start the pipeline.

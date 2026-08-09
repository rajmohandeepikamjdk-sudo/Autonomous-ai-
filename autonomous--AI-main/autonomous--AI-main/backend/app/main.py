import time

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_agent import router as agent_router
from app.config import get_settings
from app.database import init_db
from app.logging_config import logger
from app.utils.rate_limit import KeyedRateLimiter

settings = get_settings()

app = FastAPI(
    title="Autonomous AI Content Agent",
    description=(
        "Call POST /api/agent/init once. The system then researches topics, "
        "writes, reviews, fact-checks, and publishes content on its own schedule, "
        "forever, exposing results via GET /api/agent/feed."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_rate_limiter = KeyedRateLimiter(settings.API_RATE_LIMIT_PER_MIN)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.allow(client_ip):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
        )
    return await call_next(request)


@app.middleware("http")
async def timing_and_error_middleware(request: Request, call_next):
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - top-level API safety net
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    return response


@app.on_event("startup")
async def on_startup():
    init_db()
    logger.info("Database initialized. Waiting for POST /api/agent/init to begin autonomous execution.")


app.include_router(agent_router)


@app.get("/api/info")
async def info():
    return {
        "service": "Autonomous AI Content Agent",
        "docs": "/docs",
        "init": "POST /api/agent/init",
        "feed": "GET /api/agent/feed",
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# Landing page (app/static/index.html) served at "/". Mounted last so it
# never shadows the API routes or /docs above.
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

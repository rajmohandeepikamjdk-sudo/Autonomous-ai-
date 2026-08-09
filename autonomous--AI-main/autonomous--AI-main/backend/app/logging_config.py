import logging

from app.config import get_settings
from app.database import session_scope
from app.models import AgentLog

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("agent")


def log_event(agent: str, message: str, level: str = "INFO", cycle_id: str | None = None) -> None:
    """Write a structured log line to stdout AND to the agent_logs table.

    Best-effort: a DB write failure here must never take down the pipeline,
    so it's caught and only surfaced via stdout.
    """
    getattr(logger, level.lower(), logger.info)(f"[{agent}] {message}")
    try:
        with session_scope() as session:
            session.add(AgentLog(agent=agent, level=level, message=message, cycle_id=cycle_id))
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to persist log entry: {exc}")

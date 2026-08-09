import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import get_settings

settings = get_settings()

# Ensure the sqlite file's parent dir exists (e.g. ./data)
_db_path = settings.DATABASE_URL.replace("sqlite:///", "")
if _db_path and _db_path not in (":memory:",):
    os.makedirs(os.path.dirname(_db_path) or ".", exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    from app import models  # noqa: F401  (register models on Base.metadata)
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    """Provide a transactional scope for a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""
Centralized configuration. All values are overridable via environment
variables / .env file so the same image can run in demo mode (no keys) or
production mode (real LLM + real web research) without code changes.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    LLM_PROVIDER: str = "mock"  # mock | openai | anthropic | groq | ollama
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3"

    # Research
    RESEARCH_MODE: str = "offline"  # offline | web
    RESEARCH_SOURCE_URLS: str = "https://en.wikipedia.org,https://arstechnica.com"

    # Pipeline
    PIPELINE_INTERVAL_MINUTES: int = 15
    MAX_CONTENT_REVISIONS: int = 2
    LLM_RATE_LIMIT_PER_MIN: int = 20
    TOPIC_SIMILARITY_DEDUP_THRESHOLD: float = 0.86

    # Storage
    DATABASE_URL: str = "sqlite:///./data/agent.db"
    CHROMA_PERSIST_DIR: str = "./data/chroma"

    # API
    API_RATE_LIMIT_PER_MIN: int = 60
    LOG_LEVEL: str = "INFO"

    # LinkedIn (optional — publisher posts here in addition to the local feed
    # if enabled and credentials are present)
    LINKEDIN_ENABLED: bool = False
    LINKEDIN_ACCESS_TOKEN: str = ""
    LINKEDIN_PERSON_URN: str = ""  # e.g. urn:li:person:AbC123xyz
    LINKEDIN_API_VERSION: str = "202601"  # YYYYMM, see LinkedIn docs

    @property
    def research_source_list(self) -> List[str]:
        return [s.strip() for s in self.RESEARCH_SOURCE_URLS.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

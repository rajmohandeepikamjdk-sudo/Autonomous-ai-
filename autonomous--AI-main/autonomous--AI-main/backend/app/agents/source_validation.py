"""
SourceValidationAgent decides which candidate sources are trustworthy enough
to research from and cite. Runs BEFORE research so we never spend an LLM/HTTP
call researching from a source we'd reject anyway.
"""
from urllib.parse import urlparse
from typing import List

import httpx

from app.agents.base_agent import BaseAgent
from app.config import get_settings
from app.utils.retry import retryable, RetryExhaustedError

settings = get_settings()

# Domains explicitly trusted for citation. A production system would load
# this from a managed allowlist; kept inline here for transparency/demo.
TRUSTED_DOMAINS = {
    "en.wikipedia.org": 0.75,
    "arxiv.org": 0.95,
    "arstechnica.com": 0.8,
    "nature.com": 0.95,
    "www.nature.com": 0.95,
    "ieee.org": 0.9,
    "acm.org": 0.9,
    "github.com": 0.7,
    "openai.com": 0.8,
    "anthropic.com": 0.8,
}

BLOCKED_DOMAINS = {"example-spam.com", "clickbait.biz"}


class SourceValidationAgent(BaseAgent):
    name = "SourceValidationAgent"

    def domain_of(self, url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def trust_score(self, domain: str) -> float:
        return TRUSTED_DOMAINS.get(domain, 0.4)  # unknown domains get a modest default, not zero

    @retryable(max_attempts=2, base_delay=0.5)
    async def _reachable(self, url: str) -> bool:
        if settings.RESEARCH_MODE == "offline":
            return True  # no network in offline demo mode; treat as reachable
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            resp = await client.head(url)
            return resp.status_code < 400

    async def validate(self, raw_sources: List[str], cycle_id: str) -> List[str]:
        validated: List[str] = []
        for url in raw_sources:
            domain = self.domain_of(url)
            if not domain or domain in BLOCKED_DOMAINS:
                self.log(f"Rejected source {url} (blocked/invalid domain)", cycle_id=cycle_id)
                continue
            score = self.trust_score(domain)
            if score < 0.4:
                self.log(f"Rejected source {url} (trust_score={score:.2f} below threshold)", cycle_id=cycle_id)
                continue
            try:
                if not await self._reachable(url):
                    self.log(f"Rejected source {url} (unreachable)", cycle_id=cycle_id)
                    continue
            except RetryExhaustedError as exc:
                self.log(f"Rejected source {url} (reachability check failed: {exc})", "WARNING", cycle_id)
                continue
            validated.append(url)
            self.log(f"Validated source {url} (trust_score={score:.2f})", cycle_id=cycle_id)
        return validated

"""
WebResearchAgent gathers evidence for the chosen topic from validated
sources. Two modes:
  - offline: generates a structured research note per source using the LLM
    (or the deterministic MockLLM), so the whole pipeline runs with no
    internet access at all — required for a reliable hackathon demo.
  - web: actually fetches each source URL, strips it down to readable text,
    and summarizes it with the LLM.

Swapping RESEARCH_MODE in .env changes behavior without touching any other
agent — this is the "pluggable research backend" the architecture doc
promises.
"""
import re
from typing import List

import httpx

from app.agents.base_agent import BaseAgent, ResearchNote
from app.agents.source_validation import SourceValidationAgent
from app.config import get_settings
from app.utils.retry import retryable, RetryExhaustedError

settings = get_settings()

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKLINES_RE = re.compile(r"\n\s*\n+")


def html_to_text(html: str, max_chars: int = 4000) -> str:
    """Dependency-free HTML -> readable text: drops script/style blocks,
    strips tags, unescapes a few common entities, and collapses whitespace
    so the LLM summarizes prose instead of markup."""
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(ent, ch)
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINES_RE.sub("\n", text)
    return text.strip()[:max_chars]


class WebResearchAgent(BaseAgent):
    name = "WebResearchAgent"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validator = SourceValidationAgent(self.llm, self.memory)

    @retryable(max_attempts=2, base_delay=0.5)
    async def _fetch_excerpt(self, url: str) -> str:
        headers = {"User-Agent": "AutonomousContentAgent/1.0 (+research bot)"}
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return html_to_text(resp.text)

    async def research(self, topic: str, validated_sources: List[str], cycle_id: str) -> List[ResearchNote]:
        notes: List[ResearchNote] = []
        for url in validated_sources:
            domain = self._validator.domain_of(url)
            trust = self._validator.trust_score(domain)

            if settings.RESEARCH_MODE == "web":
                try:
                    raw_excerpt = await self._fetch_excerpt(url)
                except RetryExhaustedError as exc:
                    self.log(f"Fetch failed for {url}, skipping: {exc}", "WARNING", cycle_id)
                    continue
                summary_prompt = (
                    f"Topic: {topic}\nRaw page excerpt (may contain HTML noise):\n{raw_excerpt}\n\n"
                    "Summarize the 2-3 most relevant, checkable facts about the topic from this excerpt. "
                    "If nothing relevant is present, say 'NO_RELEVANT_CONTENT'."
                )
            else:
                summary_prompt = (
                    f"Topic: {topic}\nSource: {url}\n\n"
                    "Provide 2-3 plausible, checkable findings about this topic as if you had "
                    "researched this source, written as short factual bullet points."
                )

            try:
                summary = await self.llm.complete(
                    system="You are a careful research assistant. Only state things you can "
                           "attribute to the given source; never fabricate statistics.",
                    prompt=summary_prompt,
                    max_tokens=250,
                )
            except Exception as exc:  # noqa: BLE001
                self.log(f"LLM summarization failed for {url}: {exc}", "ERROR", cycle_id)
                continue

            if "NO_RELEVANT_CONTENT" in summary:
                self.log(f"No relevant content extracted from {url}", cycle_id=cycle_id)
                continue

            notes.append(ResearchNote(source_url=url, domain=domain, trust_score=trust, snippet=summary.strip()))
            self.log(f"Research note captured from {url}", cycle_id=cycle_id)

        return notes

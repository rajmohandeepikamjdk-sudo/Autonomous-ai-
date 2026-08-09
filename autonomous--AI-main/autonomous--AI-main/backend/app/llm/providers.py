import hashlib
import random
import textwrap

import httpx

from app.config import get_settings
from app.llm.base import LLMProvider
from app.utils.retry import retryable

settings = get_settings()


class OpenAIProvider(LLMProvider):
    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL

    @retryable(max_attempts=3, base_delay=1.0)
    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""


class AnthropicProvider(LLMProvider):
    def __init__(self):
        from anthropic import AsyncAnthropic
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.ANTHROPIC_MODEL

    @retryable(max_attempts=3, base_delay=1.0)
    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        return "".join(parts)


class GroqProvider(LLMProvider):
    """Groq's free tier (no credit card) — OpenAI-compatible endpoint, so we
    reuse the openai package with a different base_url instead of adding a
    new dependency."""

    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        self._model = settings.GROQ_MODEL

    @retryable(max_attempts=3, base_delay=1.0)
    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content or ""


class OllamaProvider(LLMProvider):
    def __init__(self):
        self._host = settings.OLLAMA_HOST
        self._model = settings.OLLAMA_MODEL

    @retryable(max_attempts=3, base_delay=1.0)
    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._host}/api/generate",
                json={
                    "model": self._model,
                    "prompt": f"{system}\n\n{prompt}",
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "")


class MockLLM(LLMProvider):
    """Deterministic, dependency-free provider so the whole pipeline runs
    with zero API keys and zero network access — ideal for hackathon judging
    or CI. Uses simple templating + hashing so output is stable per input
    (useful for tests) but still varies across topics.
    """

    async def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        seed = int(hashlib.sha256((system + prompt).encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        if "brainstorm" in system.lower() or "topic" in system.lower() and "brainstorm" in prompt.lower():
            candidates = [
                "Advances in on-device AI inference",
                "Open-source vector database benchmarks",
                "Energy efficiency in large language models",
                "Progress in autonomous agent orchestration",
                "New developments in retrieval-augmented generation",
                "State of WebAssembly for AI workloads",
                "Trends in synthetic data for model training",
            ]
            rng.shuffle(candidates)
            return "\n".join(candidates[:5])

        if "fact" in system.lower() and "check" in system.lower():
            # Deterministically "pass" ~85% of the time so the pipeline
            # demonstrates both the happy path and the revision path.
            verdict = "PASS" if rng.random() < 0.85 else "FAIL"
            reason = (
                "All claims map to at least one provided research note."
                if verdict == "PASS"
                else "One or more claims are not clearly supported by the research notes; soften or cite more precisely."
            )
            return f"VERDICT: {verdict}\nREASON: {reason}"

        if "review" in system.lower() or "quality" in system.lower():
            verdict = "APPROVE" if rng.random() < 0.9 else "REVISE"
            reason = (
                "Clear structure, appropriately hedged claims, good length."
                if verdict == "APPROVE"
                else "Tighten the opening paragraph and remove repeated phrasing."
            )
            return f"VERDICT: {verdict}\nREASON: {reason}"

        # Default: content-writing style completion.
        topic_line = next((l for l in prompt.splitlines() if l.lower().startswith("topic:")), "Topic: General update")
        topic = topic_line.split(":", 1)[-1].strip() or "General update"

        title = f"What's actually new in {topic}"
        body = textwrap.dedent(f"""
            {topic} has moved quickly in the last cycle. Drawing on the research
            notes gathered this run, the clearest signal is that practical adoption
            is outpacing the marketing narrative: teams are shipping smaller,
            more specialized systems rather than waiting for a single silver-bullet
            release.

            Three things stand out. First, the tooling around {topic.lower()} is
            maturing — fewer bespoke integrations, more shared conventions.
            Second, cost and latency, not raw capability, are now the binding
            constraint for most teams. Third, the open questions are shifting from
            'can we build this' to 'how do we operate this reliably,' which is a
            healthy sign of a technology leaving its hype phase.

            Worth watching next: how quickly the ecosystem converges on shared
            evaluation standards, since that's usually the leading indicator for
            when a space stabilizes.
        """).strip()
        rationale = (
            f"Selected because '{topic}' scored highest this cycle on recency and "
            f"novelty relative to recently published topics, and had at least one "
            f"validated source with concrete, checkable claims. The angle focuses on "
            f"operational maturity rather than repeating headline capability claims, "
            f"since that's the least-covered and most defensible angle given the "
            f"available research notes."
        )
        return f"TITLE: {title}\nBODY:\n{body}\nRATIONALE:\n{rationale}"


def build_llm_provider() -> LLMProvider:
    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai" and settings.OPENAI_API_KEY:
        return OpenAIProvider()
    if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicProvider()
    if provider == "groq" and settings.GROQ_API_KEY:
        return GroqProvider()
    if provider == "ollama":
        return OllamaProvider()
    # Falls back to Mock if provider misconfigured or no key present —
    # the system must never be unable to start because of a missing key.
    return MockLLM()

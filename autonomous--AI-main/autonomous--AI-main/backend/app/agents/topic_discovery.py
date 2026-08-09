"""
TopicDiscoveryAgent covers three stages of the workflow diagram:
Topic Discovery -> Trend Analysis -> Topic Ranking.

Decision it makes: "which single topic is worth researching this cycle."
"""
from typing import List, Tuple

from app.agents.base_agent import BaseAgent
from app.config import get_settings

settings = get_settings()

SEED_TOPICS = [
    "Advances in on-device AI inference",
    "Open-source vector database benchmarks",
    "Energy efficiency in large language models",
    "Progress in autonomous agent orchestration",
    "New developments in retrieval-augmented generation",
    "State of WebAssembly for AI workloads",
    "Trends in synthetic data for model training",
    "Hardware acceleration for transformer inference",
    "Evaluation methods for multi-agent systems",
    "Privacy-preserving machine learning techniques",
]


class TopicDiscoveryAgent(BaseAgent):
    name = "TopicDiscoveryAgent"

    async def discover_candidates(self, cycle_id: str) -> List[str]:
        """Discovery: combine a static seed list with an LLM brainstorm so the
        candidate pool isn't purely hardcoded."""
        try:
            raw = await self.llm.complete(
                system="You are a topic discovery agent. Brainstorm current, specific, "
                       "checkable topics in applied AI/software engineering.",
                prompt="Brainstorm 5 specific, non-generic topics worth writing a short "
                       "analysis post about today. One per line, no numbering.",
                max_tokens=200,
            )
            brainstormed = [line.strip("-• \t") for line in raw.splitlines() if line.strip()]
        except Exception as exc:  # noqa: BLE001
            self.log(f"LLM brainstorm failed, falling back to seed list only: {exc}", "WARNING", cycle_id)
            brainstormed = []

        candidates = list(dict.fromkeys(SEED_TOPICS + brainstormed))  # dedupe, preserve order
        self.log(f"Discovered {len(candidates)} candidate topics", cycle_id=cycle_id)
        return candidates

    def trend_score(self, topic: str, recent_topics: List[str]) -> float:
        """Trend analysis: a lightweight recency/frequency heuristic. A real
        deployment would swap this for actual trend-API signal (e.g. search
        volume, social mentions) — the interface (topic -> float score) is
        what matters and stays stable either way.
        """
        # Penalize topics that have been covered a lot recently (avoid
        # over-indexing one subject); otherwise treat all fresh topics equally.
        recent_count = sum(1 for t in recent_topics if t.lower() == topic.lower())
        base_score = 1.0
        penalty = 0.3 * recent_count
        return max(0.0, base_score - penalty)

    def rank_topics(self, candidates: List[str], recent_topics: List[str]) -> List[Tuple[str, float]]:
        """Ranking: score every candidate and sort descending."""
        scored = [(t, self.trend_score(t, recent_topics)) for t in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

    async def pick_topic(self, cycle_id: str) -> Tuple[str, float]:
        candidates = await self.discover_candidates(cycle_id)
        recent_topics = self.memory.recent_topics(days=7)
        ranked = self.rank_topics(candidates, recent_topics)

        for topic, score in ranked:
            # Skip topics whose semantic content is too close to something
            # already published (checked properly again after drafting, but
            # a coarse pre-check here saves a wasted research/writing cycle).
            if not self.memory.is_topic_too_similar(
                topic, topic, threshold=settings.TOPIC_SIMILARITY_DEDUP_THRESHOLD
            ):
                self.log(f"Selected topic '{topic}' (score={score:.2f})", cycle_id=cycle_id)
                self.memory.record_topic_considered(topic, score, published=False)
                return topic, score

        # Every candidate looked too similar to existing content — fall back
        # to the top-ranked one rather than stalling forever.
        topic, score = ranked[0]
        self.log(f"All candidates near-duplicate; forcing top pick '{topic}'", "WARNING", cycle_id)
        return topic, score

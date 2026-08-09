"""
ContentWriterAgent turns research notes into a draft post, including an
explicit `rationale` field explaining WHY this angle/content was chosen —
this is the agent's "reasoning" output the spec asks for, and it is stored
and served verbatim via the API rather than being thrown away after
generation.
"""
from typing import List, Optional

from app.agents.base_agent import BaseAgent, DraftPost, ResearchNote


class ContentWriterAgent(BaseAgent):
    name = "ContentWriterAgent"

    def _build_prompt(self, topic: str, notes: List[ResearchNote], prior_context: List[str],
                       revision_feedback: Optional[str]) -> str:
        notes_block = "\n".join(f"- ({n.domain}, trust={n.trust_score:.2f}): {n.snippet}" for n in notes)
        prior_block = "\n---\n".join(prior_context) if prior_context else "(none)"
        feedback_block = f"\n\nPrevious attempt was rejected. Feedback to address: {revision_feedback}" if revision_feedback else ""

        return (
            f"Topic: {topic}\n\n"
            f"Research notes gathered this cycle:\n{notes_block}\n\n"
            f"Previously published posts (avoid repeating these verbatim):\n{prior_block}"
            f"{feedback_block}\n\n"
            "Write a short analysis post (250-400 words) grounded ONLY in the research notes "
            "above. Then explain your editorial reasoning.\n\n"
            "Respond in exactly this format:\n"
            "TITLE: <one line>\n"
            "BODY:\n<the post body>\n"
            "RATIONALE:\n<2-4 sentences on why this topic/angle, and how the research notes "
            "support the claims made>"
        )

    def _parse(self, raw: str, topic: str, sources: List[str]) -> DraftPost:
        title, body, rationale = "", "", ""
        section = None
        for line in raw.splitlines():
            if line.strip().upper().startswith("TITLE:"):
                title = line.split(":", 1)[-1].strip()
                section = None
            elif line.strip().upper().startswith("BODY:"):
                section = "body"
                remainder = line.split(":", 1)[-1].strip()
                if remainder:
                    body += remainder + "\n"
            elif line.strip().upper().startswith("RATIONALE:"):
                section = "rationale"
                remainder = line.split(":", 1)[-1].strip()
                if remainder:
                    rationale += remainder + "\n"
            elif section == "body":
                body += line + "\n"
            elif section == "rationale":
                rationale += line + "\n"

        if not title:
            title = f"Notes on {topic}"
        if not body.strip():
            body = raw.strip()
        if not rationale.strip():
            rationale = "Generated from validated research notes for this topic."

        return DraftPost(
            title=title.strip(),
            body=body.strip(),
            rationale=rationale.strip(),
            topic=topic,
            sources=sources,
        )

    async def write(
        self,
        topic: str,
        notes: List[ResearchNote],
        cycle_id: str,
        revision_feedback: Optional[str] = None,
    ) -> DraftPost:
        prior_context = self.memory.writer_context(topic)
        prompt = self._build_prompt(topic, notes, prior_context, revision_feedback)
        raw = await self.llm.complete(
            system="You are a rigorous technical content writer. You never invent statistics "
                   "or attribute claims to sources that weren't provided. You write in clear, "
                   "specific, non-hype prose.",
            prompt=prompt,
            max_tokens=900,
        )
        draft = self._parse(raw, topic, [n.source_url for n in notes])
        self.log(f"Draft written for topic '{topic}' ({len(draft.body)} chars)", cycle_id=cycle_id)
        return draft

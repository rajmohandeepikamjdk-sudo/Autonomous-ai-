"""
QualityReviewerAgent self-critiques a draft for clarity, structure, length,
and hype/vagueness before it ever reaches the fact checker. Returning a
structured AgentDecision (not free text) is what lets the Orchestrator branch
reliably on the verdict.
"""
from app.agents.base_agent import BaseAgent, DraftPost, AgentDecision


class QualityReviewerAgent(BaseAgent):
    name = "QualityReviewerAgent"

    def _heuristic_checks(self, draft: DraftPost) -> AgentDecision | None:
        """Cheap, deterministic checks run before spending an LLM call —
        catches obviously broken output (empty body, no sources) instantly.
        """
        if len(draft.body.split()) < 40:
            return AgentDecision(False, "Body is too short to be a substantive post.")
        if not draft.sources:
            return AgentDecision(False, "Draft cites zero sources.")
        if draft.title.strip() == "":
            return AgentDecision(False, "Draft has no title.")
        return None

    async def review(self, draft: DraftPost, cycle_id: str) -> AgentDecision:
        heuristic = self._heuristic_checks(draft)
        if heuristic is not None:
            self.log(f"Heuristic rejection: {heuristic.reason}", "WARNING", cycle_id)
            return heuristic

        raw = await self.llm.complete(
            system="You are a strict quality reviewer for technical content. You approve only "
                   "clear, specific, non-repetitive, well-structured posts.",
            prompt=(
                f"Title: {draft.title}\n\nBody:\n{draft.body}\n\n"
                "Review this post. Respond in exactly this format:\n"
                "VERDICT: APPROVE or REVISE\n"
                "REASON: <one sentence>"
            ),
            max_tokens=150,
        )
        verdict = "APPROVE" in raw.upper()
        reason_line = next((l for l in raw.splitlines() if l.upper().startswith("REASON:")), "REASON: (none given)")
        reason = reason_line.split(":", 1)[-1].strip()
        self.log(f"Review verdict={'APPROVE' if verdict else 'REVISE'}: {reason}", cycle_id=cycle_id)
        return AgentDecision(approved=verdict, reason=reason)

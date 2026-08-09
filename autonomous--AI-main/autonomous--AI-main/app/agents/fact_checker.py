"""
FactCheckerAgent is the last line of defense before publishing: it checks
that the draft's claims are traceable to the research notes gathered this
cycle, rather than trusting the writer's own citations at face value.
"""
from typing import List

from app.agents.base_agent import BaseAgent, DraftPost, ResearchNote, AgentDecision


class FactCheckerAgent(BaseAgent):
    name = "FactCheckerAgent"

    async def check(self, draft: DraftPost, notes: List[ResearchNote], cycle_id: str) -> AgentDecision:
        if not notes:
            return AgentDecision(False, "No research notes available to verify claims against.")

        notes_block = "\n".join(f"- {n.snippet}" for n in notes)
        raw = await self.llm.complete(
            system="You are a fact checker. You are skeptical by default: you fail content "
                   "that makes claims not clearly supported by the provided research notes.",
            prompt=(
                f"Research notes:\n{notes_block}\n\n"
                f"Draft post body:\n{draft.body}\n\n"
                "Does every factual claim in the draft trace back to the research notes? "
                "Respond in exactly this format:\n"
                "VERDICT: PASS or FAIL\n"
                "REASON: <one sentence>"
            ),
            max_tokens=150,
        )
        passed = "PASS" in raw.upper() and "FAIL" not in raw.upper().split("REASON")[0]
        reason_line = next((l for l in raw.splitlines() if l.upper().startswith("REASON:")), "REASON: (none given)")
        reason = reason_line.split(":", 1)[-1].strip()
        self.log(f"Fact-check verdict={'PASS' if passed else 'FAIL'}: {reason}", cycle_id=cycle_id)
        return AgentDecision(approved=passed, reason=reason)

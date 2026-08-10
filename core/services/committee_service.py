from __future__ import annotations

from core.models.research import AgentAssessment, Vote


class CommitteeService:
    def decide(self, assessments: list[AgentAssessment]) -> tuple[Vote, int]:
        weights = {"bullish": 1, "neutral": 0, "bearish": -1}
        weighted = sum(weights[a.vote] * a.confidence for a in assessments)
        total = sum(a.confidence for a in assessments) or 1
        normalized = weighted / total
        vote: Vote = "bullish" if normalized >= .2 else "bearish" if normalized <= -.2 else "neutral"
        confidence = round(50 + abs(normalized) * 45)
        return vote, confidence
